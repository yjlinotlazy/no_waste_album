# Personal Album Quality Model

## 1. Purpose

This model answers one product question:

> Is this image worth keeping in a personal digital album or using in a memory-style presentation?

This is not the same as detecting technical quality. A technically sharp commercial photograph may be useful, but it is not automatically a good personal-album photograph. The model should learn the user's preference for memorable, informative, and personally meaningful images.

The first version is intentionally single-user and personalized. Generalization to other users is not a goal.

## 2. Product boundaries

The ML system must be separate from the existing technical quality detector.

- **Technical quality detection:** blur, insufficient resolution, severe exposure problems, and similar measurable defects.
- **Personal album quality:** whether the image is a strong candidate for the user's album or a memory film.
- **Commercial:** a domain/context tag, not a negative label. Commercial images may be technically excellent but should not dominate the personal-album model.

The model must not silently delete or hide images. It produces scores and review candidates. The user decides what to tag, hide, or delete.

## 3. Label policy

### 3.1 Positive samples

The primary positive set is:

```text
tag = 高质量 AND tag != 商业
```

These are treated as the user's hand-picked examples of personal-album quality.

The initial non-commercial set may be too small to train a useful first model. Therefore, the first bootstrap run may also sample a limited number of:

```text
tag = 高质量 AND tag = 商业
```

These are **auxiliary positives**, not equivalent labels. They should have a lower training weight, remain marked with their `商业` context feature, and be sampled in a reproducible, stratified way across folders and visual conditions. The exact sample size should be configurable; a reasonable initial cap is the smaller of 50 images or 20% of the eligible commercial set.

The model must be evaluated primarily on non-commercial personal-album examples. Commercial images are useful for visual warm-starting, but they must not define the target by volume. As more non-commercial feedback arrives, auxiliary commercial examples should be down-weighted further or removed from the active training set if they are found to distort ranking.

### 3.2 Definitive negative samples

The user can press **wrong prediction** on a model result. The system copies that image into the configured negative-sample directory and records it as an explicit negative example.

Configured paths:

- ML root: `/home/yli/Dropbox/Photos/no_waste_album/ML`
- Negative samples: `/home/yli/Dropbox/Photos/no_waste_album/ML/negative_samples`

These paths must come from `config.yaml`; they must not be hardcoded in application code.

Negative samples are intentionally independent copies. Deleting the original photo must not delete these copies or their training metadata.

### 3.3 Unlabeled data

Absence of `高质量` is **not** a negative label. Most of the library is unlabeled and should remain excluded from supervised loss until the user provides a definitive label.

The following signals are weak evidence only and must not be treated as definitive negatives without an explicit policy decision:

- hidden image;
- low visitor views;
- old image;
- technical-quality warning;
- absence of any tag.

## 4. Model strategy

Do not train a vision model from scratch. The library is too small and the feedback loop is too personal for that to be a sensible first step.

### 4.1 Initial photo scope

The first model iteration uses a deliberately defined photo pool:

- include every supported image found recursively under folders whose directory name begins with `20`;
- exclude every `raw/` directory and all of its descendants, regardless of where it appears in the path;
- do not load the entire library outside this scope into the model pipeline;
- keep the scope rule and its resulting asset count in the training-job configuration and report.

This is an eligibility scope, not a labeling rule. Every in-scope image may receive cached features, but only explicit positives, auxiliary positives, or definitive negatives participate in supervised training. Unlabeled in-scope images remain unlabeled and may be used later for inference or active-learning review.

### 4.2 Sampling strategy

Sampling has two separate purposes: building training data and choosing images for user review. They must not be conflated.

#### Feature coverage

Extract features for every in-scope image, subject to the `raw/` exclusion. This gives the system a complete searchable representation without pretending that every image has a label.

#### Bootstrap training set

- include all available primary positives (`高质量` and not `商业`), even if there are only two;
- sample auxiliary commercial positives with a fixed seed and stratification by source folder, capture period, and visual cluster;
- start with at most 30 auxiliary commercial images or 10% of the eligible commercial set, whichever is smaller;
- include all explicit negative-sample copies unless they are marked inactive;
- never convert the remaining unlabeled pool into negatives;
- attach a label source and training weight to every example so commercial auxiliary positives can be down-weighted.

With only two primary positives and no meaningful explicit negatives, do not report a normal classifier metric or present the result as a reliable model. Use a bootstrap prototype/similarity ranking until more feedback exists.

#### Active review pool

Build a review batch from the unlabeled in-scope pool using a mixture of:

- visual diversity across folders and feature clusters;
- nearest neighbors to the current positive prototype;
- uncertain or boundary cases;
- a small random exploration sample to avoid tunnel vision.

The first review batch should be deliberately small, for example 20–30 images, and should not be dominated by one year folder or one visual cluster. User actions on this batch create real labels: applying `高质量` creates a positive, while **wrong prediction** creates a definitive negative copy.

To avoid burst sequences without expensive perceptual deduplication, candidate review sampling should apply a configurable minimum time distance within the same folder and capture session. Use EXIF capture time when available, with filesystem time as a fallback. Explicitly labeled examples are never discarded by this thinning rule.

#### Later training rounds

After each feedback round, retain all active labeled examples. Apply the same temporal thinning when selecting new unlabeled review candidates, then retrain a candidate model and compare it with the active model. Perceptual near-duplicate detection is deferred unless temporal thinning proves insufficient.

### 4.3 Feature layer

Build a versioned feature vector for every eligible image. The first feature layer should combine:

- frozen visual embeddings from an installed pretrained image encoder;
- image dimensions and aspect ratio;
- technical-quality signals already produced by the quality detector;
- exposure, contrast, color, and luminance statistics;
- face/person count and coarse composition signals when available;
- tag/context features such as `商业`;
- optional user-behavior aggregates only after enough visitor data exists.

The ML image path should be aggressively downsampled: apply EXIF orientation, preserve aspect ratio, resize the longest side to a bounded working size such as 512 pixels, and then apply the encoder's normal 224–384 pixel preprocessing. Do not keep full-resolution images in memory or send them through the embedding model. Original dimensions and file size remain separate metadata, while the existing technical-quality detector may use its own resolution-aware measurements.

The feature extractor must be deterministic for a given image and feature-version. It should process images in bounded batches, cache results, and avoid recomputing unchanged files.

### 4.4 Personal scorer

Start with a small, inspectable model over frozen features:

1. logistic regression or a calibrated linear ranker when there are few labels;
2. regularized gradient-boosted trees when nonlinear interactions become useful;
3. a more complex model only if evaluation shows a clear benefit.

The model output should include:

- score in `[0, 1]`;
- model version;
- feature version;
- top contributing signals where the model supports it;
- whether the result is in-distribution or based on weak evidence.

The score is a ranking signal, not a claim of objective quality.

## 5. Data and model lifecycle

Every training run must be reproducible from recorded inputs.

### 5.1 Required records

- `TrainingExample`: asset or negative-copy ID, label source, label timestamp, feature version, and active/inactive state.
- `ModelVersion`: model ID, feature version, training job ID, training-example snapshot, configuration, metrics, and file path.
- `Prediction`: model ID, asset ID, score, timestamp, and explanation payload.
- `Feedback`: prediction ID, feedback type, resulting tag/action, and timestamp.

Predictions are disposable and rebuildable. User labels and explicit negative-sample copies are durable.

### 5.2 Deletion behavior

For normal image-derived data, deleting an original removes its catalog metadata, predictions, embeddings, and related records according to the existing deletion policy. The exception is an explicit negative-sample copy: that copy remains in the configured ML directory for training.

Training data must reference the negative copy, not depend on the deleted original path.

## 6. Job types

The Advanced Tasks page is the entry point for model management. It should have:

- left panel: complete job history;
- upper-right section: training model types;
- lower-right section: evaluation model types.

### 6.1 Training jobs

#### Personal album quality model

Inputs:

- current active primary positives;
- a configurable, lower-weight sample of auxiliary commercial positives during bootstrap;
- explicit negative samples;
- feature version;
- training configuration.

Outputs:

- a versioned model artifact;
- training metrics;
- validation metrics;
- label counts and warnings;
- model status: candidate, active, or rejected.

The first training job should refuse to run, with a clear explanation, when there are too few positives or no definitive negatives. It must not silently train on arbitrary unlabeled images.

### 6.2 Evaluation jobs

#### Personal album quality detection

Runs the selected active model over a chosen folder or library scope. It stores predictions and exposes a review page with:

- image preview;
- score;
- explanation/features;
- current tags;
- **apply `高质量`**;
- **wrong prediction**;
- pagination and filtering by score.

Applying a tag is a user action and creates/updates a training example. A prediction alone does not become a label.

#### Technical quality detection

Remains separate and uses the existing heuristic pipeline. Its results should not be mixed with personal-album model results.

## 7. Evaluation protocol

Randomly splitting near-duplicate images is unacceptable because it can make the model appear much better than it is. The first evaluation should use grouped splits where possible:

- keep visually near-identical images in the same split;
- prefer time- or folder-aware holdouts;
- report the number of positive, negative, and unlabeled examples;
- report precision at the review budget the user actually cares about, such as top 20 or top 100 candidates;
- show false positives and false negatives directly in the UI.

Important metrics:

- precision among top-ranked candidates;
- recall on explicit positive labels;
- average precision or ranking quality;
- calibration of the score;
- performance split by commercial/non-commercial context;
- coverage: how many images receive a confident prediction.

The first useful success criterion is not a generic benchmark score. It is that the top-ranked review set contains noticeably more personally valuable photos than an unranked folder browse.

## 8. Feedback loop

The result page should make feedback cheaper than browsing manually:

1. Run evaluation for a folder or the whole library.
2. Review predictions in score order.
3. Apply `高质量` to genuine positives.
4. Press **wrong prediction** for definitive negatives.
5. Retrain a new candidate model.
6. Compare the candidate against the currently active model.
7. Activate only after the review metrics improve.

Do not automatically turn every unselected prediction into a negative. That would train the model on the user's time budget and UI behavior rather than explicit preference.

## 9. First implementation plan

### Phase A — Data readiness

- define database tables for training examples, model versions, predictions, and feedback;
- connect existing `高质量`/`商业` tags to positive-example generation;
- implement negative-sample copy and feedback records;
- add feature-version metadata;
- add data-count diagnostics to the training screen.

### Phase B — Baseline model

- choose and package one pretrained embedding extractor;
- generate cached feature vectors;
- train a regularized linear model;
- persist model artifacts under the configured ML directory;
- add a real `model_training` job with progress and failure reporting;
- expose metrics and label warnings.

### Phase C — Evaluation and review

- add an `album_quality` evaluation job;
- show previews and scores in the job result page;
- implement apply-tag and wrong-prediction feedback;
- make model selection/versioning explicit;
- add evaluation metrics and candidate-vs-active comparison.

### Phase D — Iterate from evidence

- inspect false positives and false negatives;
- improve features only when a failure pattern is visible;
- compare a stronger tree-based ranker against the baseline;
- add visitor behavior only if it improves ranking without overwhelming explicit labels.

## 10. Current status

The UI layout for training and evaluation model types exists, but the personal model training and evaluation buttons are intentionally disabled until the backend lifecycle above is implemented. The existing technical quality detector and Auto Develop pipeline are separate systems and must not be presented as the personal album-quality model.
