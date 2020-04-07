# bin/bash

PYTHONPATH="." luigi  --module recommendation.task.model.trivago.trivago_logistic_model TrivagoLogisticModelInteraction --project test_fixed_trivago_contextual_bandit --data-frames-preparation-extra-params '{"filter_city": "Rio de Janeiro, Brazil", "window_hist": 10}' --n-factors 50 --learning-rate=0.001 --optimizer adam --metrics '["loss"]' --epochs 250 --obs-batch-size 5000 --val-split-type random --full-refit --early-stopping-patience 5 --batch-size 200 --num-episodes 2 --test-size 0.2 --bandit-policy random


PYTHONPATH="." luigi  --module recommendation.task.model.trivago.trivago_logistic_model TrivagoLogisticModelInteraction --project test_fixed_trivago_contextual_bandit --data-frames-preparation-extra-params '{"filter_city": "Rio de Janeiro, Brazil", "window_hist": 10}' --n-factors 50 --learning-rate=0.001 --optimizer adam --metrics '["loss"]' --epochs 250 --obs-batch-size 5000 --val-split-type random --full-refit --early-stopping-patience 5 --batch-size 200 --num-episodes 2 --test-size 0.2 --bandit-policy fixed --bandit-policy-params '{"arg": 1}' --observation "First Item"

PYTHONPATH="." luigi  --module recommendation.task.model.trivago.trivago_logistic_model TrivagoLogisticModelInteraction --project test_fixed_trivago_contextual_bandit --data-frames-preparation-extra-params '{"filter_city": "Rio de Janeiro, Brazil", "window_hist": 10}' --n-factors 50 --learning-rate=0.001 --optimizer adam --metrics '["loss"]' --epochs 250 --obs-batch-size 5000 --val-split-type random --full-refit --early-stopping-patience 5 --batch-size 200 --num-episodes 2 --test-size 0.2 --bandit-policy fixed --bandit-policy-params '{"arg": 2}' --observation "Popular Item"

PYTHONPATH="." luigi  --module recommendation.task.model.trivago.trivago_logistic_model TrivagoLogisticModelInteraction --project test_fixed_trivago_contextual_bandit --data-frames-preparation-extra-params '{"filter_city": "Rio de Janeiro, Brazil", "window_hist": 10}' --n-factors 50 --learning-rate=0.001 --optimizer adam --metrics '["loss"]' --epochs 250 --obs-batch-size 1000 --val-split-type random --full-refit --early-stopping-patience 5 --batch-size 200 --num-episodes 2 --test-size 0.2 --bandit-policy fixed --bandit-policy-params '{"arg": 3}' --observation "Correct Item"

PYTHONPATH="." luigi  --module recommendation.task.model.trivago.trivago_logistic_model TrivagoLogisticModelInteraction --project trivago_contextual_bandit --data-frames-preparation-extra-params '{"filter_city": "Rio de Janeiro, Brazil", "window_hist": 10}' --n-factors 50 --learning-rate=0.001 --optimizer adam --metrics '["loss"]' --epochs 250 --obs-batch-size 1000 --val-split-type random --full-refit --early-stopping-patience 5 --batch-size 200 --num-episodes 2 --bandit-policy model --test-size 0.2

PYTHONPATH="." luigi  --module recommendation.task.model.trivago.trivago_logistic_model TrivagoLogisticModelInteraction --project trivago_contextual_bandit --data-frames-preparation-extra-params '{"filter_city": "Rio de Janeiro, Brazil", "window_hist": 10}' --n-factors 50 --learning-rate=0.001 --optimizer adam --metrics '["loss"]' --epochs 250 --obs-batch-size 1000 --val-split-type random --full-refit --early-stopping-patience 5 --batch-size 200 --num-episodes 2 --test-size 0.2 --bandit-policy epsilon_greedy --bandit-policy-params '{"epsilon": 0.1}' 

PYTHONPATH="." luigi  --module recommendation.task.model.trivago.trivago_logistic_model TrivagoLogisticModelInteraction --project trivago_contextual_bandit --data-frames-preparation-extra-params '{"filter_city": "Rio de Janeiro, Brazil", "window_hist": 10}' --n-factors 50 --learning-rate=0.001 --optimizer adam --metrics '["loss"]' --epochs 250 --obs-batch-size 1000 --val-split-type random --full-refit --early-stopping-patience 5 --batch-size 200 --num-episodes 2 --test-size 0.2 --bandit-policy softmax_explorer --bandit-policy-params '{"logit_multiplier": 5.0}'  

PYTHONPATH="." luigi  --module recommendation.task.model.trivago.trivago_logistic_model TrivagoLogisticModelInteraction --project trivago_contextual_bandit --data-frames-preparation-extra-params '{"filter_city": "Rio de Janeiro, Brazil", "window_hist": 10}' --n-factors 50 --learning-rate=0.001 --optimizer adam --metrics '["loss"]' --epochs 250 --obs-batch-size 500 --val-split-type random --full-refit --early-stopping-patience 5 --batch-size 200 --num-episodes 2 --bandit-policy lin_ucb --bandit-policy-params '{"alpha": 1e-5}' --test-size 0.2  

PYTHONPATH="." luigi  --module recommendation.task.model.trivago.trivago_logistic_model TrivagoLogisticModelInteraction --project trivago_contextual_bandit --data-frames-preparation-extra-params '{"filter_city": "Rio de Janeiro, Brazil", "window_hist": 10}' --n-factors 50 --learning-rate=0.001 --optimizer adam --metrics '["loss"]' --epochs 250 --obs-batch-size 500 --val-split-type random --full-refit --early-stopping-patience 5 --batch-size 200 --num-episodes 2 --bandit-policy custom_lin_ucb --bandit-policy-params '{"alpha": 1e-5}'  --test-size 0.2

PYTHONPATH="." luigi  --module recommendation.task.model.trivago.trivago_logistic_model TrivagoLogisticModelInteraction --project trivago_contextual_bandit --data-frames-preparation-extra-params '{"filter_city": "Rio de Janeiro, Brazil", "window_hist": 10}' --n-factors 50 --learning-rate=0.001 --optimizer adam --metrics '["loss"]' --epochs 250 --obs-batch-size 500 --val-split-type random --full-refit --early-stopping-patience 5 --batch-size 200 --num-episodes 2 --bandit-policy explore_then_exploit --bandit-policy-params '{"explore_rounds": 1000, "decay_rate": 0.0001872157}' --test-size 0.2


PYTHONPATH="." luigi --module recommendation.task.model.evaluation EvaluateTestSetPredictions --model-module recommendation.task.model.trivago.trivago_logistic_model --model-cls TrivagoLogisticModelInteraction --model-task-id TrivagoLogisticModelInteraction_selu____epsilon_greedy_58274b531d --fairness-columns "[\"platform_idx\"]" --local-scheduler

PYTHONPATH="." luigi --module recommendation.task.model.evaluation EvaluateTestSetPredictions --model-module recommendation.task.model.trivago.trivago_logistic_model --model-cls TrivagoLogisticModelInteraction --model-task-id TrivagoLogisticModelInteraction_selu____fixed_6b9b1b73c3 --fairness-columns "[\"platform_idx\"]" --local-scheduler


# PYTHONPATH="." luigi  --module recommendation.task.model.trivago.trivago_logistic_model TrivagoLogisticModelInteraction --project trivago_contextual_bandit --data-frames-preparation-extra-params '{"filter_city": "Rio de Janeiro, Brazil", "window_hist": 10}' --n-factors 50 --learning-rate=0.001 --optimizer adam --metrics '["loss"]' --epochs 250 --obs-batch-size 3000 --val-split-type random --full-refit --early-stopping-patience 5 --batch-size 200 --num-episodes 1 --bandit-policy softmax_explorer --bandit-policy-params '{"logit_multiplier": 5.0}' --test-size 0.2

# TrivagoLogisticModelInteraction_selu____epsilon_greedy_0043dd8062  TrivagoLogisticModelInteraction_selu____model_3075be2b70
# TrivagoLogisticModelInteraction_selu____epsilon_greedy_0d90f8a4d4  TrivagoLogisticModelInteraction_selu____model_de73dbe43f
# TrivagoLogisticModelInteraction_selu____epsilon_greedy_1c92ffa67c  TrivagoLogisticModelInteraction_selu____softmax_explorer_21728877dc
# TrivagoLogisticModelInteraction_selu____epsilon_greedy_f757400165  TrivagoLogisticModelInteraction_selu____softmax_explorer_855ece5f9b
# TrivagoLogisticModelInteraction_selu____model_1ce13edfa2           TrivagoLogisticModelInteraction_selu____softmax_explorer_b881644e99
# TrivagoLogisticModelInteraction_selu____model_277da19d04

# python tools/eval_viz/extract_plots.py --models TrivagoLogisticModelInteraction_selu____epsilon_greedy_0043dd8062,TrivagoLogisticModelInteraction_selu____model_3075be2b70,TrivagoLogisticModelInteraction_selu____epsilon_greedy_0d90f8a4d4,TrivagoLogisticModelInteraction_selu____model_de73dbe43f,TrivagoLogisticModelInteraction_selu____epsilon_greedy_1c92ffa67c,TrivagoLogisticModelInteraction_selu____softmax_explorer_21728877dc,TrivagoLogisticModelInteraction_selu____epsilon_greedy_f757400165,TrivagoLogisticModelInteraction_selu____softmax_explorer_855ece5f9b,TrivagoLogisticModelInteraction_selu____model_1ce13edfa2,TrivagoLogisticModelInteraction_selu____softmax_explorer_b881644e99,TrivagoLogisticModelInteraction_selu____model_277da19d04 --legend bandit_policy,batch_size,project --output tools/eval_viz/export/sample