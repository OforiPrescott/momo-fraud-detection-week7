# Model card: MoMo fraud and intrusion detector

A short, honest description of the model behind the platform: what it is for, how it was built, how well it
works, and where it should not be trusted. Format after Mitchell et al., "Model Cards for Model Reporting".

## Model details

| | |
| --- | --- |
| Type | Gradient-boosted decision trees (XGBoost classifier), tuned |
| Output | A risk score from 0 to 1 per transaction: the estimated probability that it is fraud or an account takeover |
| Inputs | 21 features: transaction type and amount, sender/receiver balances and ledger mismatches, time of day, sender history (count, usual amount, amount vs usual), devices used by the sender, SIM change on record, receiver fan-in |
| Files | `backend/model.joblib`, checksum `backend/model.joblib.sha256` |
| Training code | `src/train_baseline_model.py`, `src/tune_and_compare_models.py` |
| Explanations | XGBoost TreeSHAP: each input's signed contribution to each score |

## Intended use

- Ranking mobile money transactions so fraud analysts review the riskiest first.
- Choosing a response per transaction: allow, watch, step-up verification, or hold and call the customer.
- Research and teaching on fraud detection that combines transaction and access (device, SIM) signals.

**Not intended for** blocking customers or freezing funds automatically without a person reviewing the
case, judging individuals outside mobile money transactions, or credit or employment decisions.

## Training data

- **Transactions:** the public PaySim1 dataset (Kaggle `ealaxi/paysim1`), 6,362,620 simulated mobile money
  transactions calibrated on real transaction logs from an African mobile money service.
- **Access layer:** simulated device IDs, login times, locations and SIM-change events joined per account
  (`src/access_event_generator.py`), because no public dataset contains them.
- **Labels:** `any_attack_flag` = PaySim's own `isFraud` OR one of three Ghana-specific attack patterns
  applied by rules (`src/attack_injector.py`): SIM-swap takeover, PIN-sharing abuse, agent collusion.
- **Split:** 80% training, 20% held-out test (1.27 million transactions), stratified by label.

## Performance (held-out test set, 1,272,524 transactions)

| Model | Precision | Recall | F1 | AUC-ROC | AUC-PR |
| --- | --- | --- | --- | --- | --- |
| XGBoost baseline | 0.494 | 0.993 | 0.660 | 0.994 | 0.943 |
| **XGBoost tuned (deployed)** | **0.487** | **0.996** | **0.654** | **0.993** | **0.942** |
| MLP neural network | 0.981 | 0.756 | 0.854 | 0.993 | 0.937 |

At the default threshold of 0.50 the deployed model catches 99.6% of labelled attacks, and about half of
its alerts are false alarms. The alert threshold in the dashboard moves along this trade-off; with labelled
data the dashboard suggests three thresholds (best balance, catch 95% of attacks, 90% of alerts real).

**Most influential inputs:** devices used by the sender (about 78% of the model's importance), then SIM
change on record and amount-related features. Device and SIM signals matter far more than money alone.

## Limitations and risks

- **Synthetic labels.** Three of the four attack labels come from rules applied to simulated access data, so
  the metrics above measure how well the model reproduces those rules, not proven real-world accuracy.
  Validate on real, independently labelled data before operational use.
- **Simulated access signals.** Real device and SIM data will be noisier. Expect lower accuracy.
- **Missing signals.** Without device or SIM information, scores rely on weaker financial signals. The
  dashboard reports this as signal coverage.
- **Drift.** Fraud patterns change. Accuracy measured once does not hold forever.
- **Fairness.** No demographic attributes are used, but device-sharing patterns may differ between
  communities (for example, shared family phones), which could raise scores for some legitimate customers.
  Review false alarms for such patterns before tightening thresholds.

## Monitoring built into the platform

- **Data drift:** every analysis computes the Population Stability Index (PSI) of each supplied input
  against the training reference sample. Under 0.10 is similar, 0.10 to 0.25 somewhat different, over 0.25
  very different; large shifts raise a finding telling the user that scores may be less reliable.
- **Signal coverage:** the share of the model's importance that the user's data actually supplied.
- **Measured accuracy:** when the data contains a confirmed-fraud column, precision and recall are measured
  on the user's own data.
- **Integrity:** the model loads only if its SHA-256 checksum matches.

## Retraining

Run the pipeline in the README (steps 1-6). The training scripts save the model together with its
checksum. Re-run `python -m pytest` before deploying a new model.
