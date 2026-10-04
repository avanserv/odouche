# Changelog

## [0.2.0](https://github.com/avanserv/odouche/compare/v0.1.0...v0.2.0) (2026-10-04)


### Features

* **lib:** Carry the session in a type that cannot print itself ([#16](https://github.com/avanserv/odouche/issues/16)) ([0e506b5](https://github.com/avanserv/odouche/commit/0e506b5bc01e8e76a802fa361cdbd40396d9078c))
* **lib:** Give the library one error hierarchy callers can catch ([#17](https://github.com/avanserv/odouche/issues/17)) ([aaf1046](https://github.com/avanserv/odouche/commit/aaf104614e62a3dbec52ef7337eb5afe611539bc))
* **lib:** Keep the session in the OS keyring with a client-side max age ([#19](https://github.com/avanserv/odouche/issues/19)) ([8b9a7e9](https://github.com/avanserv/odouche/commit/8b9a7e9af63d28bade096ac58caffc316bbe4b7d))
* **lib:** List a branch's builds and read one build ([#23](https://github.com/avanserv/odouche/issues/23)) ([5dc7dda](https://github.com/avanserv/odouche/commit/5dc7ddaf352aea6f04135a364e09253716540b2e))
* **lib:** List a project's branches with their stage ([#22](https://github.com/avanserv/odouche/issues/22)) ([96552bd](https://github.com/avanserv/odouche/commit/96552bd5752ae8a56305d81825b216aa4c003cd4))
* **lib:** List the reachable projects behind one client entry point ([#21](https://github.com/avanserv/odouche/issues/21)) ([75eeea6](https://github.com/avanserv/odouche/commit/75eeea6027666ea1c3f5a2428353ed4656c2b7ec))
* **lib:** Log in through the browser GitHub flow and store only the session ([#20](https://github.com/avanserv/odouche/issues/20)) ([1441eea](https://github.com/avanserv/odouche/commit/1441eeaf3728fe5c580dfb6c48664acb6d67957f))
* **lib:** Put every Odoo.sh request behind one transport that pins the host ([#18](https://github.com/avanserv/odouche/issues/18)) ([b759656](https://github.com/avanserv/odouche/commit/b759656232754fab26b913417eab7a3ee3042461))
* **lib:** Read and follow a build's logs ([#26](https://github.com/avanserv/odouche/issues/26)) ([1c9073c](https://github.com/avanserv/odouche/commit/1c9073ca100fea0da4689386549e5c58f93e02eb))
* **lib:** Report who the session belongs to, and log out on both sides ([#25](https://github.com/avanserv/odouche/issues/25)) ([9082d86](https://github.com/avanserv/odouche/commit/9082d86029cdb5f6d6f753e5c9d4479b78a6695b))
* **lib:** Trigger a rebuild, behind a read-only mode ([#28](https://github.com/avanserv/odouche/issues/28)) ([ebd64b9](https://github.com/avanserv/odouche/commit/ebd64b93ce897c920f79f694b2ba0ec1f20751ae))
* **lib:** Watch a build until it finishes ([#27](https://github.com/avanserv/odouche/issues/27)) ([8f8a54c](https://github.com/avanserv/odouche/commit/8f8a54cecae317cbb9fb38f883f77979f9ac3a97))


### Bug Fixes

* **lib:** Bound the wait on a keyring that shows a dialog ([#24](https://github.com/avanserv/odouche/issues/24)) ([b91ae7b](https://github.com/avanserv/odouche/commit/b91ae7b5038f20d56a9f10a129eed931a7e8b4e9))


### Documentation

* Say that docs, perf and revert commits open a patch release ([#14](https://github.com/avanserv/odouche/issues/14)) ([a91dc23](https://github.com/avanserv/odouche/commit/a91dc23fa97fa93935c852c82e256aa3e88ee28a))

## 0.1.0 (2026-10-01)


### Documentation

* Decide how the session is captured at the end of the browser login ([#11](https://github.com/avanserv/odouche/issues/11)) ([3261c9e](https://github.com/avanserv/odouche/commit/3261c9e170e5186face7a3b70c2e1082f4e7bd0a))
* Decide the library's API shape, HTTP client and models ([#13](https://github.com/avanserv/odouche/issues/13)) ([d161b97](https://github.com/avanserv/odouche/commit/d161b97acc8992fa3d784914dd81c3c758e2f17f))
* Decide what happens with no keyring backend ([#6](https://github.com/avanserv/odouche/issues/6)) ([d15fc52](https://github.com/avanserv/odouche/commit/d15fc5232f5c0b5278b7a282a0b7af948d7cdb9e))
* Map the bus websocket that carries build status changes ([#12](https://github.com/avanserv/odouche/issues/12)) ([1075b9b](https://github.com/avanserv/odouche/commit/1075b9baac287a7d483e52079deb4ea509727f6b))
* Map the Odoo.sh login flow and session from a browser capture ([#9](https://github.com/avanserv/odouche/issues/9)) ([d9ea0ad](https://github.com/avanserv/odouche/commit/d9ea0adb774db5e37acebdc00c8d1bc788ebcf3c))
* Map the project, branch, build, log and rebuild requests with fixtures ([#10](https://github.com/avanserv/odouche/issues/10)) ([d54110b](https://github.com/avanserv/odouche/commit/d54110b4059641ba771b575d94d1339476778c02))
* State the unofficial status where users install, with a dated reading of Odoo's terms ([#8](https://github.com/avanserv/odouche/issues/8)) ([bc94e0b](https://github.com/avanserv/odouche/commit/bc94e0b404e2f1d04b845718b9912fe2893a388e))
