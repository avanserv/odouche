# Changelog

## [0.7.0](https://github.com/avanserv/odouche/compare/v0.6.0...v0.7.0) (2026-10-26)


### Features

* Add a member and change a member's role with osh projects members ([#87](https://github.com/avanserv/odouche/issues/87)) ([13f2adb](https://github.com/avanserv/odouche/commit/13f2adb9340cca35a6e6510cd1738c121f15d85f))
* Change a branch's settings with osh branches settings set ([#80](https://github.com/avanserv/odouche/issues/80)) ([b6eb76e](https://github.com/avanserv/odouche/commit/b6eb76e92a7c0584c3daea699a6d90dbaf510813))
* Change a project's settings with osh projects settings set ([#84](https://github.com/avanserv/odouche/issues/84)) ([517866e](https://github.com/avanserv/odouche/commit/517866e28bf7aa90d35cfa159ec8e506ee5d4ba1))
* Check a project's health with osh projects check ([#81](https://github.com/avanserv/odouche/issues/81)) ([3073c61](https://github.com/avanserv/odouche/commit/3073c6178903e7f2392c6cafd2f4732a95d95069))
* List a branch's history with osh branches history ([#69](https://github.com/avanserv/odouche/issues/69)) ([c777fc4](https://github.com/avanserv/odouche/commit/c777fc4bff27df923e08672f838b40285f2f6a90))
* List a project's members with their role ([#85](https://github.com/avanserv/odouche/issues/85)) ([c2ca1f7](https://github.com/avanserv/odouche/commit/c2ca1f77a19feeaa91e6de7cfebf0bf6644a5a35))
* List the mails a build caught with osh builds mails ([#77](https://github.com/avanserv/odouche/issues/77)) ([9cd0161](https://github.com/avanserv/odouche/commit/9cd01617f3ea57303ae9fdbb06f0851abaf74f38))
* Move a branch between development and staging with osh branches move ([#86](https://github.com/avanserv/odouche/issues/86)) ([6ac7907](https://github.com/avanserv/odouche/commit/6ac7907640eecd9282dd4acc0d05c93139a0a1f6))
* Print the URL of a build's panels with osh builds open ([#76](https://github.com/avanserv/odouche/issues/76)) ([1c50056](https://github.com/avanserv/odouche/commit/1c50056361fcf1d5a788db19d089702f77156c71))
* Read a branch's settings as a typed model ([#74](https://github.com/avanserv/odouche/issues/74)) ([19b3534](https://github.com/avanserv/odouche/commit/19b353400db5480aed1a61d383f9af70846c64dd))
* Read a project's audit log with osh projects audit ([#82](https://github.com/avanserv/odouche/issues/82)) ([3d84a9d](https://github.com/avanserv/odouche/commit/3d84a9d00df9ea0158b63beff152a18cc3accde2))
* Read a project's settings with osh projects settings show ([#83](https://github.com/avanserv/odouche/issues/83)) ([565eaee](https://github.com/avanserv/odouche/commit/565eaee020e8c30ede41d24db074c0a0f334e3f5))
* Report the revision a build runs with osh branches revision ([#75](https://github.com/avanserv/odouche/issues/75)) ([8b5c437](https://github.com/avanserv/odouche/commit/8b5c437891178bec607598598433c566013b8e97))
* Show a project's overview with osh projects show ([#79](https://github.com/avanserv/odouche/issues/79)) ([7bf081c](https://github.com/avanserv/odouche/commit/7bf081c4d31b784ccd92045ecab57f2ab22fac16))


### Documentation

* Map branch settings, mails, panels, stage moves and project administration of Odoo.sh ([#72](https://github.com/avanserv/odouche/issues/72)) ([9a95636](https://github.com/avanserv/odouche/commit/9a95636071d1e5beae4ffd1ab24c521bfcf35178))

## [0.6.0](https://github.com/avanserv/odouche/compare/v0.5.0...v0.6.0) (2026-10-17)


### Features

* **cli:** Copy a backup from the production build with osh backups pull ([#68](https://github.com/avanserv/odouche/issues/68)) ([a644dd8](https://github.com/avanserv/odouche/commit/a644dd8219d8a7a7a06c9eb483570f2415c9e810))
* Download a backup's file with osh backups download ([#67](https://github.com/avanserv/odouche/issues/67)) ([bc751ae](https://github.com/avanserv/odouche/commit/bc751ae845170925f919cd135e66a1b83f07270d))
* List a project's backups with osh backups list ([#63](https://github.com/avanserv/odouche/issues/63)) ([3d2c0ef](https://github.com/avanserv/odouche/commit/3d2c0ef22cfe86768e62d06f71edf44233bf2a73))
* Take a branch's backup with osh backups create ([#64](https://github.com/avanserv/odouche/issues/64)) ([752b2bf](https://github.com/avanserv/odouche/commit/752b2bf822b02048e94893eb929a6a54e35fb1ff))


### Documentation

* Map the Backups tab of Odoo.sh from a browser capture ([#61](https://github.com/avanserv/odouche/issues/61)) ([c765a83](https://github.com/avanserv/odouche/commit/c765a8300520dce7a18d21041891f914f95ff315))

## [0.5.0](https://github.com/avanserv/odouche/compare/v0.4.0...v0.5.0) (2026-10-14)


### Features

* **cli:** Add osh ssh, which opens a shell on a build with the user's own ssh ([#59](https://github.com/avanserv/odouche/issues/59)) ([654a3ba](https://github.com/avanserv/odouche/commit/654a3ba64b185c14a603b07e1aa668d425f5b20c))
* Let osh ssh allow the caller's IP when ssh does not get in ([#60](https://github.com/avanserv/odouche/issues/60)) ([2e1f21d](https://github.com/avanserv/odouche/commit/2e1f21db57ba851757a6d265cbb9f65f30cb62bb))


### Documentation

* Add the manual test checklist a maintainer runs before a release ([#57](https://github.com/avanserv/odouche/issues/57)) ([60cdc9e](https://github.com/avanserv/odouche/commit/60cdc9ee5e4eef57ed17c56ed47650087f68615b))

## [0.4.0](https://github.com/avanserv/odouche/compare/v0.3.0...v0.4.0) (2026-10-05)


### Features

* **mcp:** Add a tool that reads a build's log, capped and marked as untrusted ([#51](https://github.com/avanserv/odouche/issues/51)) ([8c4c641](https://github.com/avanserv/odouche/commit/8c4c641ab394028891636247e8c3d1cb2d1358e5))
* **mcp:** Add a tool that waits for a build for a bounded time and reports progress ([#52](https://github.com/avanserv/odouche/issues/52)) ([91b1227](https://github.com/avanserv/odouche/commit/91b1227f1db6a7b662d78b05c1b64f98e42e302a))
* **mcp:** Add get_session and read the session on each call ([#47](https://github.com/avanserv/odouche/issues/47)) ([4ce04c5](https://github.com/avanserv/odouche/commit/4ce04c5018f37b2d20a78b5863c24cda9a24c93b))
* **mcp:** Add the rebuild tool behind an opt-in switch that is off by default ([#50](https://github.com/avanserv/odouche/issues/50)) ([7f3edb1](https://github.com/avanserv/odouche/commit/7f3edb1b7afc8e7c1373088cff13b7943e8808a2))
* **mcp:** Add tools to list projects, branches and builds, and to read one build ([#49](https://github.com/avanserv/odouche/issues/49)) ([6cc6033](https://github.com/avanserv/odouche/commit/6cc6033361cde0d353c58a70d3d02c048ff824f0))


### Documentation

* **mcp:** Add a Claude Code hook that approves the read-only tools ([#53](https://github.com/avanserv/odouche/issues/53)) ([896c282](https://github.com/avanserv/odouche/commit/896c282861807f7a13c362ed8e394911967f5b44))
* **mcp:** Generate the tool reference from the server and add a setup guide ([#55](https://github.com/avanserv/odouche/issues/55)) ([15ef0c7](https://github.com/avanserv/odouche/commit/15ef0c7459b58875d9012975d8a0eb5e42184dbb))
* Name the session and log tools of the MCP server in the README ([#56](https://github.com/avanserv/odouche/issues/56)) ([7fce31b](https://github.com/avanserv/odouche/commit/7fce31be3f2a9d29d0554b929a5145b74dc59cda))

## [0.3.0](https://github.com/avanserv/odouche/compare/v0.2.0...v0.3.0) (2026-10-05)


### Features

* **cli:** Add osh auth login, logout and status ([#36](https://github.com/avanserv/odouche/issues/36)) ([afcf3a0](https://github.com/avanserv/odouche/commit/afcf3a0c420c955caaf353a01b5bb0e644cb84ed))
* **cli:** Add osh branches list ([#39](https://github.com/avanserv/odouche/issues/39)) ([220311f](https://github.com/avanserv/odouche/commit/220311f015c87bc151a8d634626dbbffeef04467))
* **cli:** Add osh builds list and osh builds show ([#40](https://github.com/avanserv/odouche/issues/40)) ([83dcc52](https://github.com/avanserv/odouche/commit/83dcc5299a21777857e71bce50b9af405c7cb341))
* **cli:** Add osh builds rebuild ([#45](https://github.com/avanserv/odouche/issues/45)) ([610039c](https://github.com/avanserv/odouche/commit/610039cd61b32b2aceca970876a4c6e2d6c7413e))
* **cli:** Add osh builds watch ([#41](https://github.com/avanserv/odouche/issues/41)) ([30f2807](https://github.com/avanserv/odouche/commit/30f2807b0ad2f6f050c307b6d930e0fcc618eb98))
* **cli:** Add osh logs ([#42](https://github.com/avanserv/odouche/issues/42)) ([c70ec57](https://github.com/avanserv/odouche/commit/c70ec578b82522e898cf8ce53b8e6e15498569af))
* **cli:** Add osh projects list ([#37](https://github.com/avanserv/odouche/issues/37)) ([1788bcb](https://github.com/avanserv/odouche/commit/1788bcbeb46d08bc8b4849b1e0d98fdf4c4663d1))
* **cli:** Map library errors to messages and exit codes ([#33](https://github.com/avanserv/odouche/issues/33)) ([1b74c7e](https://github.com/avanserv/odouche/commit/1b74c7e793364ef415ff74bf45a2c6350ce2d9bd))
* **cli:** Render results as a table or JSON through one output layer ([#35](https://github.com/avanserv/odouche/issues/35)) ([7e9924b](https://github.com/avanserv/odouche/commit/7e9924b4801857f01b6be5536a6558a19aa2838d))
* **cli:** Resolve the project and branch from a flag, the environment or the git checkout ([#38](https://github.com/avanserv/odouche/issues/38)) ([215a1f3](https://github.com/avanserv/odouche/commit/215a1f3a7d8170dd8b0841bd5742f06357e3e5a7))


### Documentation

* **cli:** Generate the command reference and write the guide ([#44](https://github.com/avanserv/odouche/issues/44)) ([7b1cca1](https://github.com/avanserv/odouche/commit/7b1cca1f97636684141a854fc6891195213d0a5b))

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

* **lib:** Document the library with a tested guide and a complete reference ([#32](https://github.com/avanserv/odouche/issues/32)) ([2fcd4fb](https://github.com/avanserv/odouche/commit/2fcd4fb9852a0b7113c477d5aa03476d2f6efbbe))
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
