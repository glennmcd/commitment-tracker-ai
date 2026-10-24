# Changelog

## [0.8.0](https://github.com/glennmcd/commitment-tracker-ai/compare/v0.7.0...v0.8.0) (2026-10-24)


### Features

* add the two-stage extractor ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** add --offline and rescore ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** add batch import with resolver checks ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** add blind review ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** add eval-audio make, add, upload and fetch ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** add eval-compare ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** add eval-export-site ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** add eval-gate and the baseline ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** add eval-sets ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** add promote and the review agreement summary ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** add set manifests, canonical hashes and --set ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** score transcribed audio against text items ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** store predicted spans and provenance scores ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **infra:** add the evaluation audio bucket ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **web:** add the evaluation overview and run pages ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **web:** add the items and compare pages ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))


### Bug Fixes

* **eval:** align transcribed turns in order ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** keep other configurations when updating the baseline ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** keep review alive when taking a label needs more fields ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** read JSONL safely and find long near-duplicates ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **eval:** retry transcription after a failed or timed-out job ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))
* **web:** publish runs only against the set version they scored ([c863377](https://github.com/glennmcd/commitment-tracker-ai/commit/c86337793f0c803af1c537838c3fb8c5f6a7afd6))

## [0.7.0](https://github.com/glennmcd/commitment-tracker-ai/compare/v0.6.1...v0.7.0) (2026-10-24)


### Features

* add demo GIF to README ([a1e6bed](https://github.com/glennmcd/commitment-tracker-ai/commit/a1e6bed8e2144dd81bb6ad224cc08a2167da27b4))
* add demo GIF to README ([b5e4398](https://github.com/glennmcd/commitment-tracker-ai/commit/b5e439857c80dc003a5fbe7b792cf99f8e234f72))
* **evaluation:** implement Part 3 design for evaluation ([e3dea36](https://github.com/glennmcd/commitment-tracker-ai/commit/e3dea36b7eca087baf242b3cab2a0fefa2e1f6ab))
* **evaluation:** implement Part 3 design for evaluation ([5d45282](https://github.com/glennmcd/commitment-tracker-ai/commit/5d45282a582e200ab8598ea7c618cfb24f86ef79))

## [0.6.1](https://github.com/glennmcd/commitment-tracker-ai/compare/v0.6.0...v0.6.1) (2026-10-23)


### Bug Fixes

* add missing newline at end of .cdk.json ([6a0e589](https://github.com/glennmcd/commitment-tracker-ai/commit/6a0e589b1b9bcf77abbada7bf78da1c566c64df0))

## [0.6.0](https://github.com/glennmcd/commitment-tracker-ai/compare/v0.5.0...v0.6.0) (2026-10-23)


### Features

* add e2e testing job with Playwright in CI workflow ([c1e5935](https://github.com/glennmcd/commitment-tracker-ai/commit/c1e5935425f7359be9de7a915bac7567135062b0))
* add password management script and tests ([70fc2d7](https://github.com/glennmcd/commitment-tracker-ai/commit/70fc2d7fa8e52907412bdeb8da4fdb976ef9f235))
* add password management script and tests ([75cdb12](https://github.com/glennmcd/commitment-tracker-ai/commit/75cdb12c4f73e4eaf2e1dd2a39947182f7ad4a87))
* add S3 upload perm for presigned POST in ApiStack ([324dbd1](https://github.com/glennmcd/commitment-tracker-ai/commit/324dbd16e1976b68d647d13fd36fc815fa84b28c))
* add S3 upload perm for presigned POST in ApiStack ([ba0b4fa](https://github.com/glennmcd/commitment-tracker-ai/commit/ba0b4fa719e868113749460b5d9138e260556938))


### Bug Fixes

* update CI workflow to use npm for bun installation ([f6aed9f](https://github.com/glennmcd/commitment-tracker-ai/commit/f6aed9fcf1b0fc7b2eb15719868a4b0846bef5eb))

## [0.5.0](https://github.com/glennmcd/commitment-tracker-ai/compare/v0.4.0...v0.5.0) (2026-10-23)


### Features

* implement link source and pw handling ([f6a2a91](https://github.com/glennmcd/commitment-tracker-ai/commit/f6a2a910959e33a90ba18d63eb522ef7195f47c2))
* implement link source and pw handling ([e0f502f](https://github.com/glennmcd/commitment-tracker-ai/commit/e0f502f52b407ec6b5eb7612b9c70dca0191df63))

## [0.4.0](https://github.com/glennmcd/commitment-tracker-ai/compare/v0.3.0...v0.4.0) (2026-10-23)


### Features

* implement site password protection for API endpoints ([0068ba2](https://github.com/glennmcd/commitment-tracker-ai/commit/0068ba230537587067eaf286ef82bb5e5283c82d))
* implement site password protection for API endpoints ([57f29af](https://github.com/glennmcd/commitment-tracker-ai/commit/57f29af75f29f70ed0f6818f66b6d55c8d161f15))
* **web:** show the release version and metrics ([26f9ac0](https://github.com/glennmcd/commitment-tracker-ai/commit/26f9ac01b8d1cef12061d57ad6ad1d4d624efcb3))
* **web:** show the release version and metrics ([1eef213](https://github.com/glennmcd/commitment-tracker-ai/commit/1eef2130bfcf0693d02e6de21edae1736e3fd319))

## [0.3.0](https://github.com/glennmcd/commitment-tracker-ai/compare/v0.2.0...v0.3.0) (2026-10-23)


### Features

* add Lambda handlers and SSM settings ([98300e1](https://github.com/glennmcd/commitment-tracker-ai/commit/98300e1d628e702f007cdaf021a866d2b952a8a1))
* add the AWS batch transcriber ([cf5aa8b](https://github.com/glennmcd/commitment-tracker-ai/commit/cf5aa8b716f3a00a27314737075f578f268e10a7))
* add the job store ([528b536](https://github.com/glennmcd/commitment-tracker-ai/commit/528b5368df7d7bccfc2d37e76be89dcc28feda38))
* add the job worker ([b2f751d](https://github.com/glennmcd/commitment-tracker-ai/commit/b2f751da0b7f912d025ac7250cb4f0225e926225))
* **api:** add optional turn timestamps ([30b7132](https://github.com/glennmcd/commitment-tracker-ai/commit/30b7132cf7175245dec166e6671e7a926ad56c64))
* **api:** add per-client rate limiting ([c030bd1](https://github.com/glennmcd/commitment-tracker-ai/commit/c030bd1159e4254d8ca4701423164e915667cfba))
* **api:** add presigned uploads and WAV validation ([162bad8](https://github.com/glennmcd/commitment-tracker-ai/commit/162bad8598397611ab3089099cdae976f6ca4286))
* **api:** add span feedback ([407f956](https://github.com/glennmcd/commitment-tracker-ai/commit/407f9567167e0b1c3df6e8e200f2fea5518b05f8))
* **api:** add the daily spend cap ([4785a34](https://github.com/glennmcd/commitment-tracker-ai/commit/4785a34ddc889b0efaa3f0263abe59c2b56c04a9))
* **api:** add the job resource ([a620951](https://github.com/glennmcd/commitment-tracker-ai/commit/a6209517a7109198b0ba602dacb86e7f7326e207))
* emit the daily spend as a CloudWatch metric ([2ccdc18](https://github.com/glennmcd/commitment-tracker-ai/commit/2ccdc18b5e1edff6b97fd4777f927639302268fa))
* **infra:** add the Amplify web stack ([46a5166](https://github.com/glennmcd/commitment-tracker-ai/commit/46a5166f0b353c5d07c41c7220495596b1be7494))
* **infra:** add the API stack ([adea794](https://github.com/glennmcd/commitment-tracker-ai/commit/adea794bbb29d3c8e404736a52d8ce6a4b5b0736))
* **infra:** add the budget kill switch and alarms ([8c1f4ad](https://github.com/glennmcd/commitment-tracker-ai/commit/8c1f4ada3656acda96173e121c1c1081cf9c4dc9))
* **infra:** let -c choose the model ([cb99868](https://github.com/glennmcd/commitment-tracker-ai/commit/cb998684b3b39f6a9c88c1678a939bc221a37212))
* map Transcribe output to timed turns ([29e0a27](https://github.com/glennmcd/commitment-tracker-ai/commit/29e0a27957160a500268aff8ec16d0b283ed87cb))
* **samples:** add sample data and audio files ([df96e74](https://github.com/glennmcd/commitment-tracker-ai/commit/df96e74c28b0e00e092b6632aadf9a1d418b4026))
* **web:** add prompt chips and the Playwright test ([88fd681](https://github.com/glennmcd/commitment-tracker-ai/commit/88fd681f14321f63ee9883fa28b533707e394471))
* **web:** add recording and upload ([3a9bd50](https://github.com/glennmcd/commitment-tracker-ai/commit/3a9bd50d23af3a9bdab7ee042820fd2742e9033a))
* **web:** add sample clips ([251d647](https://github.com/glennmcd/commitment-tracker-ai/commit/251d6479159ad68a7279ddae1164a6f3e1c618d1))
* **web:** add span feedback ([feb9c1c](https://github.com/glennmcd/commitment-tracker-ai/commit/feb9c1c0c014efe5f6cb8d09461aada9d693ae02))
* **web:** add text mode and the results view ([028cafa](https://github.com/glennmcd/commitment-tracker-ai/commit/028cafa09f1cbb63b4c309598ee4464107054996))
* **web:** scaffold the Next.js app and the typed client ([f7aa97e](https://github.com/glennmcd/commitment-tracker-ai/commit/f7aa97e57b149c144a746bd164d308792d367457))


### Bug Fixes

* **infra:** route each endpoint so CORS preflights succeed ([ff656dc](https://github.com/glennmcd/commitment-tracker-ai/commit/ff656dccb0a05c8f18e7d88addda1f68bfc76a95))
* **infra:** wrap the Amplify custom headers in the monorepo app key ([654b87a](https://github.com/glennmcd/commitment-tracker-ai/commit/654b87ac9e5017abfac31fabf297fb2698c959d6))
* store job records without computed span fields ([26a3413](https://github.com/glennmcd/commitment-tracker-ai/commit/26a3413f1e1023d2f07303ed51e26b551d4419f5))
* upt lint cmd for concise output and chng allowAgentCommits ([36afc84](https://github.com/glennmcd/commitment-tracker-ai/commit/36afc8463f5164f90d2b0189fa181c2499848d53))
* **web:** key transcript pieces by their offset ([bddb3e1](https://github.com/glennmcd/commitment-tracker-ai/commit/bddb3e1c491384efcc9c260ce4bf4a0fa7a0aab4))


### Documentation

* add ADRs 0002-0007 for Part 2 ([96a68ce](https://github.com/glennmcd/commitment-tracker-ai/commit/96a68cea9c4a25c01459acc50ad14d6f11d30a5e))
* add the deploy guide ([b064505](https://github.com/glennmcd/commitment-tracker-ai/commit/b064505d5882b702d15e114f86cd33619bc9468c))
* add the Part 2 brief and design ([865ca8c](https://github.com/glennmcd/commitment-tracker-ai/commit/865ca8cce5bc6c25422f621bc1bc9a9ff138940b))
* describe the demo, architecture and deployment in the README ([6ec74dc](https://github.com/glennmcd/commitment-tracker-ai/commit/6ec74dcc922b00df010a10b97d27fb8e003b29c6))
* exclude the eval group from the Lambda export ([9cc0d13](https://github.com/glennmcd/commitment-tracker-ai/commit/9cc0d13c2ed9876e333890932a47c880c3b96ade))
* note the Git Bash path rewrite for the SSM parameter name ([9d5dde8](https://github.com/glennmcd/commitment-tracker-ai/commit/9d5dde8bc2f9ecb78ca509ca068c91cec6b4b364))
* record the Transcribe latency test ([4504285](https://github.com/glennmcd/commitment-tracker-ai/commit/4504285e6459d6ba609c2e37573e42282ea4090d))
* use Polly standard voices for the sample clips ([784cc89](https://github.com/glennmcd/commitment-tracker-ai/commit/784cc89309141185b5d89efd1601c8803c072bff))
* use the g26work2 profile name in the SCP guide ([2baa94f](https://github.com/glennmcd/commitment-tracker-ai/commit/2baa94fd98bf5d8d21767ddd0edd82912433bd22))

## [0.2.0](https://github.com/glennmcd/commitment-tracker-ai/compare/v0.1.0...v0.2.0) (2026-10-22)


### Features

* **api:** add /analyze, /health and the exported OpenAPI schema ([2f470ae](https://github.com/glennmcd/commitment-tracker-ai/commit/2f470aeea8e0540e68f22f9f788dfac7924920bb))
* **eval:** add runner, metrics and reports ([2f1aae4](https://github.com/glennmcd/commitment-tracker-ai/commit/2f1aae4e43300061210140d4998f7d1420f64a6d))
* **eval:** seed dev set with the 24 spec utterances ([912c91f](https://github.com/glennmcd/commitment-tracker-ai/commit/912c91f635dd03c336f3e2903c97970f73085d35))
* **extractor:** add Anthropic adapter ([1de346d](https://github.com/glennmcd/commitment-tracker-ai/commit/1de346dea116959a999f0bd24a15aaa2ffafec75))
* **extractor:** add deterministic date resolver ([4a67375](https://github.com/glennmcd/commitment-tracker-ai/commit/4a673758bdc5689adcca373d607df79572809cb8))
* **extractor:** add prompt v1 and model adapter protocol ([ab94592](https://github.com/glennmcd/commitment-tracker-ai/commit/ab94592b078055e49979b38607bd64962c085ab9))
* **extractor:** resolve "before &lt;date&gt;" to the day before ([081d2da](https://github.com/glennmcd/commitment-tracker-ai/commit/081d2dae8b84dde64641f9bdf83b6bc671486409))
* **extractor:** validate, retry and quote-check model output ([13a8aa3](https://github.com/glennmcd/commitment-tracker-ai/commit/13a8aa3e248b64c014512ed63d4fa6df2d6712aa))
* **schemas:** add request, span and response models ([d7241d4](https://github.com/glennmcd/commitment-tracker-ai/commit/d7241d42f2d9586235ce5aa7f30b0c5fd54bfd56))


### Bug Fixes

* **api:** show the app's log lines under uvicorn ([55b7da1](https://github.com/glennmcd/commitment-tracker-ai/commit/55b7da151b8a74f6e7bf5611e6e351db80a86361))


### Documentation

* add Part 1 extraction call design ([963a4ea](https://github.com/glennmcd/commitment-tracker-ai/commit/963a4eaa44381b4eb8a873c78a169e014e1bff4b))
* add README with setup, labels, API and evaluation ([853dd9a](https://github.com/glennmcd/commitment-tracker-ai/commit/853dd9ab4d616661575682eab8c4b6f18fc18f42))
* document releases and add ADR 0001 ([ead4d53](https://github.com/glennmcd/commitment-tracker-ai/commit/ead4d539bc95f4d9a0eae12a874027f474f91eec))
