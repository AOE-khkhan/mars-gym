import abc
import functools
import gc
import json
import logging
import os
import pickle
import random
import shutil
from contextlib import redirect_stdout
from copy import deepcopy
from multiprocessing import Pool
from typing import Type, Dict, List, Optional, Tuple, Union, Any

import luigi
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchbearer
from torch.nn.init import xavier_normal
from torch.optim import Adam, RMSprop, SGD
from torch.optim.adadelta import Adadelta
from torch.optim.adagrad import Adagrad
from torch.optim.adamax import Adamax
from torch.optim.optimizer import Optimizer
from torch.utils.data import DataLoader
from torch.utils.data._utils.collate import default_convert
from torch.utils.data.dataset import Dataset, ChainDataset
from torchbearer import Trial
from torchbearer.callbacks import GradientNormClipping
from torchbearer.callbacks.checkpointers import ModelCheckpoint
from torchbearer.callbacks.csv_logger import CSVLogger
from torchbearer.callbacks.early_stopping import EarlyStopping
from torchbearer.callbacks.tensor_board import TensorBoard
from tqdm import tqdm

from mars_gym.cuda import CudaRepository
from mars_gym.data.dataset import (
    preprocess_interactions_data_frame,
    preprocess_metadata_data_frame,
    literal_eval_array_columns,
    InteractionsDataset,
)
from mars_gym.gym.envs.recsys import ITEM_METADATA_KEY
from mars_gym.meta_config import Column, IOType, ProjectConfig
from mars_gym.model.abstract import RecommenderModule
from mars_gym.model.agent import BanditAgent
from mars_gym.model.bandit import BanditPolicy
from mars_gym.torch.data import NoAutoCollationDataLoader, FasterBatchSampler
from mars_gym.torch.init import lecun_normal_init, he_init
from mars_gym.torch.loss import (
    ImplicitFeedbackBCELoss,
    CounterfactualRiskMinimization,
    FocalLoss,
)
from mars_gym.torch.optimizer import RAdam
from mars_gym.torch.summary import summary
from mars_gym.utils.files import (
    get_params_path,
    get_weights_path,
    get_interaction_dir,
    get_params,
    get_history_path,
    get_tensorboard_logdir,
    get_task_dir,
    get_test_set_predictions_path,
    get_index_mapping_path,
)
from mars_gym.utils.index_mapping import (
    create_index_mapping,
    create_index_mapping_from_arrays,
    transform_with_indexing,
)
from mars_gym.utils.plot import plot_history
from mars_gym.utils import files
from mars_gym.utils.reflection import load_attr

logging.basicConfig(
    format="%(asctime)s : %(levelname)s : %(message)s", level=logging.INFO
)

TORCH_OPTIMIZERS = dict(
    adam=Adam,
    rmsprop=RMSprop,
    sgd=SGD,
    adadelta=Adadelta,
    adagrad=Adagrad,
    adamax=Adamax,
    radam=RAdam,
)
TORCH_LOSS_FUNCTIONS = dict(
    mse=nn.MSELoss,
    nll=nn.NLLLoss,
    bce=nn.BCELoss,
    mlm=nn.MultiLabelMarginLoss,
    implicit_feedback_bce=ImplicitFeedbackBCELoss,
    crm=CounterfactualRiskMinimization,
    focal_loss=FocalLoss,
)
TORCH_ACTIVATION_FUNCTIONS = dict(
    relu=F.relu, selu=F.selu, tanh=F.tanh, sigmoid=F.sigmoid, linear=F.linear
)
TORCH_WEIGHT_INIT = dict(
    lecun_normal=lecun_normal_init, he=he_init, xavier_normal=xavier_normal
)
TORCH_DROPOUT_MODULES = dict(dropout=nn.Dropout, alpha=nn.AlphaDropout)

SEED = 42

DEFAULT_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


class _BaseModelTraining(luigi.Task, metaclass=abc.ABCMeta):
    project: str = luigi.Parameter(
        description="Should be like config.trivago_contextual_bandit",
    )

    sample_size: int = luigi.IntParameter(default=-1)
    minimum_interactions: int = luigi.FloatParameter(default=5)
    session_test_size: float = luigi.FloatParameter(default=0.10)
    test_size: float = luigi.FloatParameter(default=0.2)
    dataset_split_method: str = luigi.ChoiceParameter(
        choices=["holdout", "column", "time", "k_fold"], default="time"
    )
    test_split_type: str = luigi.ChoiceParameter(
        choices=["random", "time"], default="random"
    )
    val_size: float = luigi.FloatParameter(default=0.2)
    n_splits: int = luigi.IntParameter(default=5)
    split_index: int = luigi.IntParameter(default=0)
    data_frames_preparation_extra_params: dict = luigi.DictParameter(default={})
    sampling_strategy: str = luigi.ChoiceParameter(
        choices=["oversample", "undersample", "none"], default="none"
    )
    balance_fields: List[str] = luigi.ListParameter(default=[])
    sampling_proportions: Dict[str, Dict[str, float]] = luigi.DictParameter(default={})
    use_sampling_in_validation: bool = luigi.BoolParameter(default=False)
    eq_filters: Dict[str, any] = luigi.DictParameter(default={})
    neq_filters: Dict[str, any] = luigi.DictParameter(default={})
    isin_filters: Dict[str, any] = luigi.DictParameter(default={})
    seed: int = luigi.IntParameter(default=SEED)
    observation: str = luigi.Parameter(default="")

    negative_proportion: int = luigi.FloatParameter(0.0)

    @property
    def cache_attrs(self):
        return [
            "_test_dataset",
            "_val_dataset",
            "_train_dataset",
            "_test_data_frame",
            "_val_data_frame",
            "_train_data_frame",
            "_metadata_data_frame",
        ]

    def requires(self):
        return self.prepare_data_frames

    @property
    def prepare_data_frames(self):
        return self.project_config.prepare_data_frames_task(
            session_test_size=self.session_test_size,
            sample_size=self.sample_size,
            minimum_interactions=self.minimum_interactions,
            test_size=self.test_size,
            dataset_split_method=self.dataset_split_method,
            test_split_type=self.test_split_type,
            val_size=self.val_size,
            n_splits=self.n_splits,
            split_index=self.split_index,
            sampling_strategy=self.sampling_strategy,
            sampling_proportions=self.sampling_proportions,
            balance_fields=self.balance_fields
            or self.project_config.default_balance_fields,
            use_sampling_in_validation=self.use_sampling_in_validation,
            eq_filters=self.eq_filters,
            neq_filters=self.neq_filters,
            isin_filters=self.isin_filters,
            seed=self.seed,
            **self.data_frames_preparation_extra_params,
        )

    def output(self):
        return luigi.LocalTarget(get_task_dir(self.__class__, self.task_id))

    @property
    def project_config(self) -> ProjectConfig:
        if not hasattr(self, "_project_config"):
            self._project_config = deepcopy(load_attr(self.project, ProjectConfig))
            if (
                self.loss_function == "crm"
                and self.project_config.propensity_score_column_name
                not in self.project_config.auxiliar_output_columns
            ):
                self._project_config.auxiliar_output_columns = [
                    *self._project_config.auxiliar_output_columns,
                    Column(
                        self.project_config.propensity_score_column_name, IOType.NUMBER
                    ),
                ]
        return self._project_config

    def _save_params(self):
        with open(get_params_path(self.output().path), "w") as params_file:
            json.dump(
                self.param_kwargs, params_file, default=lambda o: dict(o), indent=4
            )

    @property
    def train_data_frame_path(self) -> str:
        return self.input()[0].path

    @property
    def val_data_frame_path(self) -> str:
        return self.input()[1].path

    @property
    def test_data_frame_path(self) -> str:
        return self.input()[2].path

    @property
    def metadata_data_frame_path(self) -> Optional[str]:
        if len(self.input()) > 3:
            return self.input()[3].path
        else:
            return None

    @property
    def metadata_data_frame(self) -> Optional[pd.DataFrame]:
        if not hasattr(self, "_metadata_data_frame"):
            self._metadata_data_frame = (
                pd.read_csv(self.metadata_data_frame_path)
                if self.metadata_data_frame_path
                else None
            )
            if self._metadata_data_frame is not None:
                literal_eval_array_columns(
                    self._metadata_data_frame, self.project_config.metadata_columns
                )
            #
            transform_with_indexing(
                self._metadata_data_frame, self.index_mapping, self.project_config
            )
        return self._metadata_data_frame

    @property
    def embeddings_for_metadata(self) -> Optional[Dict[str, np.ndarray]]:
        if not hasattr(self, "_embeddings_for_metadata"):
            # from IPython import embed; embed()
            self._embeddings_for_metadata = (
                preprocess_metadata_data_frame(
                    self.metadata_data_frame, self.project_config
                )
                if self.metadata_data_frame is not None
                else None
            )
        return self._embeddings_for_metadata

    @property
    def train_data_frame(self) -> pd.DataFrame:
        if not hasattr(self, "_train_data_frame"):
            self._train_data_frame = preprocess_interactions_data_frame(
                pd.read_csv(self.train_data_frame_path), self.project_config
            )

        # Needed in case index_mapping was invoked before
        if not hasattr(self, "_creating_index_mapping") and not hasattr(
            self, "_train_data_frame_indexed"
        ):
            transform_with_indexing(
                self._train_data_frame, self.index_mapping, self.project_config
            )
            self._train_data_frame_indexed = True
        return self._train_data_frame

    @property
    def val_data_frame(self) -> pd.DataFrame:
        if not hasattr(self, "_val_data_frame"):
            self._val_data_frame = preprocess_interactions_data_frame(
                pd.read_csv(self.val_data_frame_path), self.project_config
            )

        # Needed in case index_mapping was invoked before
        if not hasattr(self, "_creating_index_mapping") and not hasattr(
            self, "_val_data_frame_indexed"
        ):
            transform_with_indexing(
                self._val_data_frame, self.index_mapping, self.project_config
            )
            self._val_data_frame_indexed = True
        return self._val_data_frame

    @property
    def test_data_frame(self) -> pd.DataFrame:
        if not hasattr(self, "_test_data_frame"):
            self._test_data_frame = preprocess_interactions_data_frame(
                pd.read_csv(self.test_data_frame_path), self.project_config
            )
        # Needed in case index_mapping was invoked before
        if not hasattr(self, "_creating_index_mapping") and not hasattr(
            self, "_test_data_frame_indexed"
        ):
            transform_with_indexing(
                self._test_data_frame, self.index_mapping, self.project_config
            )
            self._test_data_frame_indexed = True
        return self._test_data_frame

    def get_data_frame_for_indexing(self) -> pd.DataFrame:
        return pd.concat([self.train_data_frame, self.val_data_frame])

    @property
    def index_mapping(self) -> Dict[str, Dict[Any, int]]:
        if not hasattr(self, "_index_mapping"):
            index_mapping_path = get_index_mapping_path(self.output().path)
            if os.path.exists(index_mapping_path):
                with open(index_mapping_path, "rb") as f:
                    self._index_mapping = pickle.load(f)
            else:
                self._creating_index_mapping = True
                df = self.get_data_frame_for_indexing()

                self._index_mapping = {
                    column.name: create_index_mapping(df[column.name].values)
                    for column in self.project_config.all_columns
                    if column.type == IOType.INDEXABLE and not column.same_index_as
                }
                self._index_mapping.update(
                    {
                        column.name: create_index_mapping_from_arrays(
                            df[column.name].values
                        )
                        for column in self.project_config.all_columns
                        if column.type == IOType.INDEXABLE_ARRAY
                        and not column.same_index_as
                    }
                )
                for column in self.project_config.all_columns:
                    if column.same_index_as:
                        self._index_mapping[column.name] = self._index_mapping[
                            column.same_index_as
                        ]
                with open(index_mapping_path, "wb") as f:
                    pickle.dump(self._index_mapping, f)
                del self._creating_index_mapping
        return self._index_mapping

    @property
    def reverse_index_mapping(self) -> Dict[str, Dict[int, Any]]:
        return {
            key: {value_: key_ for key_, value_ in mapping.items()}
            for key, mapping in self.index_mapping.items()
        }

    @property
    def train_dataset(self) -> Dataset:
        if not hasattr(self, "_train_dataset"):
            self._train_dataset = self.project_config.dataset_class(
                data_frame=self.train_data_frame,
                embeddings_for_metadata=self.embeddings_for_metadata,
                project_config=self.project_config,
                index_mapping=self.index_mapping,
                negative_proportion=self.negative_proportion,
            )
        return self._train_dataset

    @property
    def val_dataset(self) -> Dataset:
        if not hasattr(self, "_val_dataset"):
            self._val_dataset = self.project_config.dataset_class(
                data_frame=self.val_data_frame,
                embeddings_for_metadata=self.embeddings_for_metadata,
                project_config=self.project_config,
                index_mapping=self.index_mapping,
                negative_proportion=self.negative_proportion,
            )
        return self._val_dataset

    @property
    def test_dataset(self) -> Dataset:
        if not hasattr(self, "_test_dataset"):
            self._test_dataset = self.project_config.dataset_class(
                data_frame=self.test_data_frame,
                embeddings_for_metadata=self.embeddings_for_metadata,
                project_config=self.project_config,
                index_mapping=self.index_mapping,
                negative_proportion=0.0,
            )
        return self._test_dataset

    @property
    def vocab_size(self):
        if not hasattr(self, "_vocab_size"):
            self._vocab_size = int(self.train_data_frame.iloc[0]["vocab_size"])
        return self._vocab_size

    @property
    def n_users(self) -> int:
        if not hasattr(self, "_n_users"):
            self._n_users = (
                max(self.index_mapping[self.project_config.user_column.name].values())
                + 1
            )
        return self._n_users

    @property
    def n_items(self) -> int:
        if not hasattr(self, "_n_items"):
            self._n_items = (
                max(self.index_mapping[self.project_config.item_column.name].values())
                + 1
            )
        return self._n_items

    @abc.abstractmethod
    def train(self):
        pass

    def cache_cleanup(self):
        for a in self.cache_attrs:
            if hasattr(self, a):
                delattr(self, a)

    def seed_everything(self):
        random.seed(self.seed)
        os.environ["PYTHONHASHSEED"] = str(self.seed)
        np.random.seed(self.seed)
        torch.manual_seed(self.seed)
        torch.cuda.manual_seed(self.seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False

    def run(self):
        self.seed_everything()

        os.makedirs(self.output().path, exist_ok=True)
        self._save_params()
        try:
            self.train()
        except Exception:
            shutil.rmtree(self.output().path)
            raise
        finally:
            gc.collect()
            if self.device == "cuda":
                CudaRepository.put_available_device(self.device_id)


class TorchModelTraining(_BaseModelTraining, metaclass=abc.ABCMeta):
    recommender_module_class: str = luigi.Parameter(
        description="Should be like mars_gym.model.trivago.trivago_models.SimpleLinearModel",
    )
    recommender_extra_params: Dict[str, Any] = luigi.DictParameter(default={})

    device: str = luigi.ChoiceParameter(choices=["cpu", "cuda"], default=DEFAULT_DEVICE)

    batch_size: int = luigi.IntParameter(default=500)
    epochs: int = luigi.IntParameter(default=100)
    optimizer: str = luigi.ChoiceParameter(
        choices=TORCH_OPTIMIZERS.keys(), default="adam"
    )
    optimizer_params: dict = luigi.DictParameter(default={})
    learning_rate: float = luigi.FloatParameter(1e-3)
    loss_function: str = luigi.ChoiceParameter(
        choices=TORCH_LOSS_FUNCTIONS.keys(), default="mse"
    )
    loss_function_params: dict = luigi.DictParameter(default={})
    gradient_norm_clipping: float = luigi.FloatParameter(default=0.0)
    gradient_norm_clipping_type: float = luigi.IntParameter(default=2)
    early_stopping_patience: int = luigi.IntParameter(default=5)
    early_stopping_min_delta: float = luigi.FloatParameter(default=1e-3)
    monitor_metric: str = luigi.Parameter(default="val_loss")
    monitor_mode: str = luigi.Parameter(default="min")
    generator_workers: int = luigi.IntParameter(default=0)
    pin_memory: bool = luigi.BoolParameter(default=False)
    policy_estimator_extra_params: dict = luigi.DictParameter(default={})

    metrics = luigi.ListParameter(default=["loss"])

    @property
    def resources(self):
        return {"cuda": 1} if self.device == "cuda" else {}

    @property
    def device_id(self):
        if not hasattr(self, "_device_id"):
            if self.device == "cuda":
                self._device_id = CudaRepository.get_avaliable_device()
            else:
                self._device_id = None
        return self._device_id

    @property
    def module_class(self) -> Type[RecommenderModule]:
        if not hasattr(self, "_module_class"):
            self._module_class = load_attr(
                self.recommender_module_class, Type[RecommenderModule]
            )
        return self._module_class

    @property
    def all_recommender_extra_params(self) -> Dict[str, Any]:
        return self.recommender_extra_params

    def create_module(self) -> nn.Module:
        return self.module_class(
            project_config=self.project_config,
            index_mapping=self.index_mapping,
            **self.all_recommender_extra_params,
        )

    def train(self):
        if self.device == "cuda":
            torch.cuda.set_device(self.device_id)

        train_loader = self.get_train_generator()
        val_loader = self.get_val_generator()
        module = self.create_module()

        summary_path = os.path.join(self.output().path, "summary.txt")
        with open(summary_path, "w") as summary_file:
            with redirect_stdout(summary_file):
                sample_input = self.get_sample_batch()
                summary(module, sample_input)
            summary(module, sample_input)

        sample_data = self.train_data_frame.sample(100)
        sample_data.to_csv(os.path.join(self.output().path, "sample_train.csv"))

        trial = self.create_trial(module)

        try:
            trial.with_generators(
                train_generator=train_loader, val_generator=val_loader
            ).run(epochs=self.epochs)
        except KeyboardInterrupt:
            print("Finishing the training at the request of the user...")

        history_df = pd.read_csv(get_history_path(self.output().path))

        plot_history(history_df).savefig(
            os.path.join(self.output().path, "history.jpg")
        )

        self.after_fit()
        self.evaluate()
        self.cache_cleanup()

    def get_sample_batch(self):
        return default_convert(self.train_dataset[0][0])

    def after_fit(self):
        pass

    def evaluate(self):
        module = self.get_trained_module()
        val_loader = self.get_val_generator()

        print("================== Evaluate ========================")
        trial = (
            Trial(
                module,
                self._get_optimizer(module),
                self._get_loss_function(),
                callbacks=[],
                metrics=self.metrics,
            )
            .to(self.torch_device)
            .with_generators(val_generator=val_loader)
            .eval()
        )

        print(
            json.dumps((trial.evaluate(data_key=torchbearer.VALIDATION_DATA)), indent=4)
        )

    def create_trial(self, module: nn.Module) -> Trial:
        loss_function = self._get_loss_function()
        trial = Trial(
            module,
            self._get_optimizer(module),
            loss_function,
            callbacks=self._get_callbacks(),
            metrics=self.metrics,
        ).to(self.torch_device)
        if hasattr(loss_function, "torchbearer_state"):
            loss_function.torchbearer_state = trial.state
        return trial

    def _get_loss_function(self):
        return TORCH_LOSS_FUNCTIONS[self.loss_function](**self.loss_function_params)

    def _get_optimizer(self, module) -> Optimizer:
        return TORCH_OPTIMIZERS[self.optimizer](
            module.parameters(), lr=self.learning_rate, **self.optimizer_params
        )

    def _get_callbacks(self):
        callbacks = [
            *self._get_extra_callbacks(),
            ModelCheckpoint(
                get_weights_path(self.output().path),
                save_best_only=True,
                monitor=self.monitor_metric,
                mode=self.monitor_mode,
            ),
            EarlyStopping(
                patience=self.early_stopping_patience,
                min_delta=self.early_stopping_min_delta,
                monitor=self.monitor_metric,
                mode=self.monitor_mode,
            ),
            CSVLogger(get_history_path(self.output().path)),
            TensorBoard(get_tensorboard_logdir(self.task_id), write_graph=False),
        ]
        if self.gradient_norm_clipping:
            callbacks.append(
                GradientNormClipping(
                    self.gradient_norm_clipping, self.gradient_norm_clipping_type
                )
            )
        return callbacks

    def _get_extra_callbacks(self):
        return []

    def get_trained_module(self) -> nn.Module:
        module = self.create_module().to(self.torch_device)
        state_dict = torch.load(
            get_weights_path(self.output().path), map_location=self.torch_device
        )
        module.load_state_dict(state_dict["model"])
        module.eval()
        return module

    @property
    def torch_device(self) -> torch.device:
        if not hasattr(self, "_torch_device"):
            if self.device == "cuda":
                self._torch_device = torch.device(f"cuda:{self.device_id}")
            else:
                self._torch_device = torch.device("cpu")
        return self._torch_device

    def get_train_generator(self) -> DataLoader:
        batch_sampler = FasterBatchSampler(
            self.train_dataset, self.batch_size, shuffle=True
        )
        return NoAutoCollationDataLoader(
            self.train_dataset,
            batch_sampler=batch_sampler,
            num_workers=self.generator_workers,
            pin_memory=self.pin_memory if self.device == "cuda" else False,
        )

    def get_val_generator(self) -> Optional[DataLoader]:
        if len(self.val_data_frame) == 0:
            return None
        batch_sampler = FasterBatchSampler(
            self.val_dataset, self.batch_size, shuffle=False
        )
        return NoAutoCollationDataLoader(
            self.val_dataset,
            batch_sampler=batch_sampler,
            num_workers=self.generator_workers,
            pin_memory=self.pin_memory if self.device == "cuda" else False,
        )

    def get_test_generator(self) -> DataLoader:
        batch_sampler = FasterBatchSampler(
            self.test_dataset, self.batch_size, shuffle=False
        )
        return NoAutoCollationDataLoader(
            self.test_dataset,
            batch_sampler=batch_sampler,
            num_workers=self.generator_workers,
            pin_memory=True if self.device == "cuda" else False,
        )


class SupervisedModelTraining(TorchModelTraining):
    bandit_policy_class: str = luigi.Parameter(
        default="mars_gym.model.bandit.ModelPolicy",
        description="Should be like mars_gym.model.bandit.EpsilonGreedy",
    )
    bandit_policy_params: Dict[str, Any] = luigi.DictParameter(default={})

    def create_agent(self) -> BanditAgent:
        bandit_class = load_attr(self.bandit_policy_class, Type[BanditPolicy])
        bandit = bandit_class(
            reward_model=self.get_trained_module(), **self.bandit_policy_params
        )
        return BanditAgent(bandit)

    @property
    def unique_items(self) -> List[int]:
        if not hasattr(self, "_unique_items"):
            self._unique_items = self.get_data_frame_for_indexing()[
                self.project_config.item_column.name
            ].unique()
        return self._unique_items

    @property
    def obs_columns(self) -> List[str]:
        if not hasattr(self, "_obs_columns"):
            self._obs_columns = [self.project_config.user_column.name] + [
                column.name for column in self.project_config.other_input_columns
            ]
        return self._obs_columns

    def _get_arm_indices(self, ob: dict) -> Union[List[int], np.ndarray]:
        if self.project_config.available_arms_column_name:
            arm_indices = np.flatnonzero(
                ob[self.project_config.available_arms_column_name]
            )
        else:
            arm_indices = self.unique_items[:100]
        random.shuffle(arm_indices)

        return arm_indices

    def _get_arm_scores(self, agent: BanditAgent, ob_dataset: Dataset) -> List[float]:
        batch_sampler = FasterBatchSampler(ob_dataset, self.batch_size, shuffle=False)
        generator = NoAutoCollationDataLoader(
            ob_dataset,
            batch_sampler=batch_sampler,
            num_workers=self.generator_workers,
            pin_memory=self.pin_memory if self.device == "cuda" else False,
        )

        trial = (
            Trial(
                agent.bandit.reward_model,
                criterion=lambda *args: torch.zeros(
                    1, device=self.torch_device, requires_grad=True
                ),
            )
            .with_test_generator(generator)
            .to(self.torch_device)
            .eval()
        )

        with torch.no_grad():
            model_output: Union[torch.Tensor, Tuple[torch.Tensor]] = trial.predict(
                verbose=0
            )

        scores_tensor: torch.Tensor = model_output if isinstance(
            model_output, torch.Tensor
        ) else model_output[0][0]
        scores: List[float] = scores_tensor.cpu().numpy().reshape(-1).tolist()

        return scores

    def _create_ob_data_frame(self, ob: dict, arm_indices: List[int]) -> pd.DataFrame:
        data = [
            {**ob, self.project_config.item_column.name: arm_index}
            for arm_index in arm_indices
        ]
        ob_df = pd.DataFrame(
            columns=self.obs_columns + [self.project_config.item_column.name], data=data
        )

        ob_df = self._fill_hist_columns(ob_df)

        if self.project_config.output_column.name not in ob_df.columns:
            ob_df[self.project_config.output_column.name] = 1
        for auxiliar_output_column in self.project_config.auxiliar_output_columns:
            if auxiliar_output_column.name not in ob_df.columns:
                ob_df[auxiliar_output_column.name] = 0

        return ob_df

    def _fill_hist_columns(self, ob_df: pd.DataFrame) -> pd.DataFrame:
        if self.project_config.hist_view_column_name not in ob_df:
            ob_df[self.project_config.hist_view_column_name] = 0
        if self.project_config.hist_output_column_name not in ob_df:
            ob_df[self.project_config.hist_output_column_name] = 0
        return ob_df

    def _prepare_for_agent(
        self, agent: BanditAgent, obs: List[Dict[str, Any]]
    ) -> Tuple[List[Tuple[np.ndarray, ...]], List[List[int]], List[List[float]]]:
        arm_indices_list = [self._get_arm_indices(ob) for ob in obs]
        ob_dfs = [
            self._create_ob_data_frame(ob, arm_indices)
            for ob, arm_indices in zip(obs, arm_indices_list)
        ]
        obs_dataset = InteractionsDataset(
            pd.concat(ob_dfs), obs[0][ITEM_METADATA_KEY], self.project_config, self.index_mapping
        )

        arm_contexts_list: List[Tuple[np.ndarray, ...]] = []
        i = 0
        for ob_df in ob_dfs:
            arm_contexts_list.append(obs_dataset[i : i + len(ob_df)][0])
            i += len(ob_df)

        if agent.bandit.reward_model:
            all_arm_scores = self._get_arm_scores(agent, obs_dataset)
            arm_scores_list = []
            i = 0
            for ob_df in ob_dfs:
                arm_scores_list.append(all_arm_scores[i : i + len(ob_df)])
                i += len(ob_df)
        else:
            arm_scores_list = [
                agent.bandit.calculate_scores(arm_indices, arm_contexts)
                for arm_indices, arm_contexts in zip(
                    arm_indices_list, arm_contexts_list
                )
            ]
        return arm_contexts_list, arm_indices_list, arm_scores_list

    def _act(self, agent: BanditAgent, ob: dict) -> int:
        arm_contexts_list, arm_indices_list, arm_scores_list = self._prepare_for_agent(
            agent, [ob]
        )

        return agent.act(arm_indices_list[0], arm_contexts_list[0], arm_scores_list[0])

    def clean(self):
        if hasattr(self, "_train_dataset"):
            del self._train_dataset

        if hasattr(self, "_test_dataset"):
            del self._test_dataset

        if hasattr(self, "_train_data_frame"):
            del self._train_data_frame

        gc.collect()

    def _save_test_set_predictions(self, agent: BanditAgent) -> None:
        print("Saving test set predictions...")
        obs: List[Dict[str, Any]] = self.test_data_frame.to_dict("records")
        self.clean()

        for ob in tqdm(obs, total=len(obs)):
            if self.embeddings_for_metadata is not None:
                ob[ITEM_METADATA_KEY] = self.embeddings_for_metadata
            else:
                ob[ITEM_METADATA_KEY] = None

            if self.project_config.available_arms_column_name:
                available_arms = ob[self.project_config.available_arms_column_name]
                # TODO
                if len(available_arms) == 0:
                    available_arms = [ob[self.project_config.item_column.name]]

                items = np.zeros(np.max(available_arms) + 1)
                items[available_arms] = 1
                ob[self.project_config.available_arms_column_name] = items

        arm_contexts_list, arm_indices_list, arm_scores_list = self._prepare_for_agent(
            agent, obs
        )

        sorted_actions_list = []
        proba_actions_list = []

        for arm_contexts, arm_indices, arm_scores in tqdm(
            zip(arm_contexts_list, arm_indices_list, arm_scores_list),
            total=len(arm_contexts_list),
        ):
            sorted_actions, proba_actions = agent.rank(
                arm_indices, arm_contexts, arm_scores
            )
            sorted_actions_list.append(sorted_actions)
            proba_actions_list.append(proba_actions)

        action_scores_list = [
            list(reversed(sorted(action_scores))) for action_scores in arm_scores_list
        ]

        del obs

        self.test_data_frame["sorted_actions"] = sorted_actions_list
        self.test_data_frame["prob_actions"] = proba_actions_list
        self.test_data_frame["action_scores"] = action_scores_list

        self.test_data_frame.to_csv(
            get_test_set_predictions_path(self.output().path), index=False
        )

    def after_fit(self):
        if self.test_size > 0:
            self._save_test_set_predictions(self.create_agent())


def load_torch_model_training_from_task_dir(
    model_cls: Type[TorchModelTraining], task_dir: str
) -> TorchModelTraining:
    return model_cls(**get_params(task_dir))


def load_torch_model_training_from_task_id(
    model_cls: Type[TorchModelTraining], task_id: str
) -> TorchModelTraining:

    task_dir = get_task_dir(model_cls, task_id)
    if not os.path.exists(task_dir):
        task_dir = get_interaction_dir(model_cls, task_id)

    return load_torch_model_training_from_task_dir(model_cls, task_dir)
