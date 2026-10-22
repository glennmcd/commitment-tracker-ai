# Changelog

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
