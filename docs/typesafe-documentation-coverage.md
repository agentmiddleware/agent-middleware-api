# TypeSafe documentation coverage

Review date: 2026-10-03. Applied guidance: [TypeSafe evaluation](typesafe-evaluation.md).
Repository base: `bc6178768afa9bdf09245344f0fb83bcb21db20e`.

## Scope and evidence

The [documentation index](https://docs.typesafe.ai/llms.txt) contained 111
unique Markdown pages. All 111 were retrieved and reviewed by the coordinating
agent and specialist reviewers: 20 core/API pages, 53 JavaScript reference pages,
13 Python/shared-SDK pages, and 25 cookbook/supplemental pages. Three linked
legal policies were also reviewed, for 114 sources total.

A separate integrity fetch of the indexed pages returned HTTP 200 for 111/111,
totaling 1,186,221 raw UTF-8 bytes.
The hashes below identify those response bytes, including MDX presentation code;
they are retrieval fingerprints, not signatures or vendor attestations.
Indexed integrity fetch window:
`2026-10-03T22:56:43.714Z` through
`2026-10-03T22:56:46.788Z`.
Legal-page hashes come from their review fetches on the same date.

Review covered prose, contracts, sample code, and published textual results.
Presentation-only MDX components were omitted from some reading views.
Embedded videos, interactive playground behavior, opaque playground payloads,
and external SDK repositories were not evaluated. This is the complete
**indexed documentation** review, not every page linked anywhere on the web.

No dependency was installed and no inference or authenticated API request was
made. One delegated reviewer executed selected public SDE helper functions
locally in memory with a stubbed model class, despite its read-only/no-execution
brief. That scope deviation was stopped; it made no network calls or file
changes. It established an example-code missing-field defect, not model quality.
No other cookbook execution is claimed.

Reading completion is an agent review record, not a runtime test. Vendor
benchmarks, accuracy, prices, and service defaults remain vendor statements;
they are not AMW measurements. Raw third-party documentation is not vendored.

## Indexed pages

All rows: HTTP 200; review complete. Groups identify the review responsibility,
not a supported AMW integration.

| Page | Group | Raw bytes | SHA-256 |
|---|---|---:|---|
| [agent-skill.md](https://docs.typesafe.ai/agent-skill.md) | Python | 5911 | `58150a9cecb9b9727c6039b14e0dfea7f2e3cb9be6ee14611b7df9cc8e0c94c7` |
| [api.md](https://docs.typesafe.ai/api.md) | Core | 11344 | `6b760275f89341fe15cff80c28aacae94d7d0c0c99afcd987ec0bca680b5713a` |
| [concepts/how-to-build-with-system-one.md](https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md) | Core | 41034 | `9f5a20ac39383695d554bf812b365ed4b70622b8e5ac10484dce290469c68972` |
| [concepts/state.md](https://docs.typesafe.ai/concepts/state.md) | Core | 3669 | `8ed5a4e719cf2414759fed92463c203855f1fb4bf02b685746cd4858481375a5` |
| [concepts/system-one.md](https://docs.typesafe.ai/concepts/system-one.md) | Core | 3903 | `a9a536be92d9c906c02f8aee6c28622a563bbe4a1ead5078d9bc48fe3612f265` |
| [concepts/use-case-map.md](https://docs.typesafe.ai/concepts/use-case-map.md) | Examples | 11155 | `4dd749d672520170b99113c870ca8aff93e16212075b210c8797849d8ba24fbc` |
| [confidence.md](https://docs.typesafe.ai/confidence.md) | Core | 24090 | `5c325ec0c0b69e78129406ca7c5d3aef113bce365abd34985b8674cd278c81be` |
| [cookbooks.md](https://docs.typesafe.ai/cookbooks.md) | Examples | 5944 | `45f9d361808ab00c9bd7d9fbd814ecaa7e557836dc1d4f739cdb31480a08cc54` |
| [cookbooks/autoformat.md](https://docs.typesafe.ai/cookbooks/autoformat.md) | Examples | 40995 | `cb5db3e079d337d0b5923e1d122a9c65612e342061d42939ed1aea130f3a58ba` |
| [cookbooks/autoresearch_feature_discovery.md](https://docs.typesafe.ai/cookbooks/autoresearch_feature_discovery.md) | Examples | 71468 | `24e0854e5a5846c269142d2a57abfb8aa90d63c37231b03036ed08f1e9989b72` |
| [cookbooks/citation_check.md](https://docs.typesafe.ai/cookbooks/citation_check.md) | Examples | 15367 | `76bdeead0640f4963815aba7c4cbafe7812cb619b678606998f1735a808fd3f6` |
| [cookbooks/classification_using_confidence.md](https://docs.typesafe.ai/cookbooks/classification_using_confidence.md) | Examples | 30818 | `6b5bed0126a9df1dac941760a57f82b5a336d866b03a0634ff4a845c4c146f35` |
| [cookbooks/classifying_rag_passages.md](https://docs.typesafe.ai/cookbooks/classifying_rag_passages.md) | Examples | 32505 | `c0e8075add0790efb51ea298281c5fb1a2510a108012449c425e5af4a61c66e1` |
| [cookbooks/consistency_choice_cookbook.md](https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook.md) | Examples | 49510 | `a1a8481c676fd4b6419a9f26feeacd1f223624cb17f438ac8b640597bbc03900` |
| [cookbooks/consistency_noul_cookbook.md](https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook.md) | Examples | 32065 | `7d0a90fc22b71703d4dc38a901032afbe5a22bb911134d553654f143a9a6fd41` |
| [cookbooks/date_extraction_cookbook.md](https://docs.typesafe.ai/cookbooks/date_extraction_cookbook.md) | Examples | 19957 | `28565d596103548298c3a26f3dce11c1d2e9e21e59608e84044cfb7134914cca` |
| [cookbooks/entity_alignment.md](https://docs.typesafe.ai/cookbooks/entity_alignment.md) | Examples | 16676 | `4042aa07e351032b4ebf0799b25df9427845f7860afaebe8d8e387aa495b8db0` |
| [cookbooks/function_calling.md](https://docs.typesafe.ai/cookbooks/function_calling.md) | Examples | 18973 | `c03cd58ac34dca4e282bfda4b21df943f27c0d652d49ad6b8bac1afa47f8856c` |
| [cookbooks/hierarchical_classification.md](https://docs.typesafe.ai/cookbooks/hierarchical_classification.md) | Examples | 35776 | `c88074597b5d49a2a19b35626688467f8a8186a730ec0074041858499aff2455` |
| [cookbooks/llm_guardrails.md](https://docs.typesafe.ai/cookbooks/llm_guardrails.md) | Examples | 22613 | `aa9dbed8188e07606e74fc0866f0b23493d8f5f3cdea65a3edefcfb55881f43e` |
| [cookbooks/parallel_questions.md](https://docs.typesafe.ai/cookbooks/parallel_questions.md) | Examples | 48597 | `1f4574474139321a1e05b31887a18ffe1dd3235169276aa4b600c6ebc110aee8` |
| [cookbooks/pre_parsed_value_extraction_cookbook.md](https://docs.typesafe.ai/cookbooks/pre_parsed_value_extraction_cookbook.md) | Examples | 12655 | `a5242dbf4df6dcae3bbf374047026714c1801cdc126b39bc4bca99212dd1a1c9` |
| [cookbooks/rerank_typesafe.md](https://docs.typesafe.ai/cookbooks/rerank_typesafe.md) | Examples | 26180 | `7d8969ab0d851fb0296d5e86c53eac03f3ba3dc0b779aecd7903604f51a6ce11` |
| [cookbooks/sde_cascade.md](https://docs.typesafe.ai/cookbooks/sde_cascade.md) | Examples | 32780 | `90ab0294cb0d83b0ece3343edf11c6d492ce0236f4e21b434bbdbcb7c5500b74` |
| [cookbooks/semantic_find.md](https://docs.typesafe.ai/cookbooks/semantic_find.md) | Examples | 37957 | `92b23c001081fd4244a99e7162e87f8152306865c2906af8922fcc29587171d6` |
| [cookbooks/skill_suggestion.md](https://docs.typesafe.ai/cookbooks/skill_suggestion.md) | Examples | 39391 | `c59bf591db3d45e20b90a93a4526775e5188c479c6366b9a4267cb37ab51fc90` |
| [demos.md](https://docs.typesafe.ai/demos.md) | Examples | 701 | `4faa2fa2b75622e6eb908fa0356e3dec8ec3ffb5a254bae30d378339ce4d288c` |
| [demos/smart-home.md](https://docs.typesafe.ai/demos/smart-home.md) | Examples | 3938 | `ea60b22f89269d95d1b974f72ddfa755a0aafa0d3b162882d10cde3d4b3379e6` |
| [introduction.md](https://docs.typesafe.ai/introduction.md) | Core | 4227 | `df1ed7ec91afcaa1d35f3a4f9d4b3ba33d2e816e472c64a1870f8ed885963c67` |
| [introduction/coding-agents.md](https://docs.typesafe.ai/introduction/coding-agents.md) | Core | 3934 | `72b81af8a34379d9c6d0f632aabc6b69b98dad6a85371ffd088687e844841a80` |
| [introduction/machine-learning-primer.md](https://docs.typesafe.ai/introduction/machine-learning-primer.md) | Examples | 6693 | `62f4354cfcdc00c5ec3e4865bc6b6a79900042c26c3afea0e67d88537e980121` |
| [introduction/quickstart.md](https://docs.typesafe.ai/introduction/quickstart.md) | Core | 7166 | `ff4d66b466bc4a4748ae911fc51e1dc489ee363876263b4e271eb1f22b8cc9aa` |
| [legal.md](https://docs.typesafe.ai/legal.md) | Examples | 1168 | `cc96ee6f2d53a89a76b21dc0df6102e5982d2583aa9ad95971d8bebc9de55897` |
| [model-jaggedness/jev-1.13.md](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md) | Examples | 9346 | `5d471be7c8d2a359a81979b7bcf2c2fab536a198d4e50155c4233380d5c03986` |
| [models.md](https://docs.typesafe.ai/models.md) | Core | 6684 | `15351adaab85874b5f1a942fc2fdf3c7b3ecadcc936d580793d734855a0038f3` |
| [patterns.md](https://docs.typesafe.ai/patterns.md) | Core | 1590 | `2e4e92e424f23e4e0af622f61551cf43d2d608591f2d14bb776b86fe9a92a523` |
| [patterns/composite-scoring.md](https://docs.typesafe.ai/patterns/composite-scoring.md) | Core | 13658 | `043dc1d58d91a823f9da3ef47d018340b357ed78857a94a56b5220718d106147` |
| [patterns/confidence-routing.md](https://docs.typesafe.ai/patterns/confidence-routing.md) | Core | 12281 | `3d156395f69856e2cdadb9405a23fa3f08b5ecf4274c3cd81d844d8bbe860b0e` |
| [patterns/fan-out.md](https://docs.typesafe.ai/patterns/fan-out.md) | Core | 14080 | `f78bd972e2f24338c03c99f2ab4c2d1c46666e27c085ee703b661a96b6da7543` |
| [patterns/intent-routing.md](https://docs.typesafe.ai/patterns/intent-routing.md) | Core | 13557 | `b4a6d42a9a1d90211bc1ab81539520157630e5d404c918360b26db53afc41bae` |
| [primitives.md](https://docs.typesafe.ai/primitives.md) | Core | 24185 | `fe67e1062c34ffef8f64ba5e541d00159214cd15c48f6c19ef46c25a6357a294` |
| [primitives/advanced.md](https://docs.typesafe.ai/primitives/advanced.md) | Core | 18943 | `650a61153fe3d16619e57c8f81fc03b570d663c40dd2fe94df6e57db6c906f62` |
| [primitives/choice.md](https://docs.typesafe.ai/primitives/choice.md) | Core | 26907 | `ae9c49b815ee30b28ed851e22b63041130fba50ae41368d41a5d80b571f383bb` |
| [primitives/noul.md](https://docs.typesafe.ai/primitives/noul.md) | Core | 26498 | `bf5d8c6700fbd9272ce27b53a6439d598e7915cdf505704ac7c827c6175ecb88` |
| [primitives/score.md](https://docs.typesafe.ai/primitives/score.md) | Core | 43770 | `a0a39b9c01f5ac3616efae071bf23f879bbe3fb12b0af2169932dbb71dd83d32` |
| [sdk.md](https://docs.typesafe.ai/sdk.md) | Python | 936 | `874e852726f1aa5567e69e2b748d7432b691d45a755b0cdbfb4fddcc5e838d35` |
| [sdk/javascript.md](https://docs.typesafe.ai/sdk/javascript.md) | JavaScript | 1415 | `269059683486938fd93c9ef675ed93d7b38c5ce9151b0baa892837bb79e55cc2` |
| [sdk/javascript/api.md](https://docs.typesafe.ai/sdk/javascript/api.md) | JavaScript | 3440 | `8a593d34f66b64f099d6610aae78f460dbcb3afc5e3b58ff649ad076b28b6f42` |
| [sdk/javascript/api/classes/APIConnectionError.md](https://docs.typesafe.ai/sdk/javascript/api/classes/APIConnectionError.md) | JavaScript | 1001 | `c0c606422c5421971b5807f66bd67a12e3d292d157debedfcc23b9845a802b78` |
| [sdk/javascript/api/classes/APIError.md](https://docs.typesafe.ai/sdk/javascript/api/classes/APIError.md) | JavaScript | 2303 | `5d7a12451f08d98e507f3b7ff2b32a835827c9fcdd9d8cb3f246500d99a0e4a4` |
| [sdk/javascript/api/classes/APIPromise.md](https://docs.typesafe.ai/sdk/javascript/api/classes/APIPromise.md) | JavaScript | 3686 | `2a1c74759dfd10c8fed4e051802cfb59cc2f8720889f010440a59e97a1f6cae4` |
| [sdk/javascript/api/classes/APITimeoutError.md](https://docs.typesafe.ai/sdk/javascript/api/classes/APITimeoutError.md) | JavaScript | 1056 | `dfb22f9e8b0a5b40c156569ff18bae410fca0b6da8000717dc1cd96f0d7b574d` |
| [sdk/javascript/api/classes/APIUserAbortError.md](https://docs.typesafe.ai/sdk/javascript/api/classes/APIUserAbortError.md) | JavaScript | 893 | `dac5bfd48bd2be4077d1e2d6e3c26105b345b3ca250400eee832a3d5eadad747` |
| [sdk/javascript/api/classes/AuthenticationError.md](https://docs.typesafe.ai/sdk/javascript/api/classes/AuthenticationError.md) | JavaScript | 2511 | `6059e775cfd5efcfbaba12fcd19a48225bc97edb5723ebbada0e8b3c2c68c8b8` |
| [sdk/javascript/api/classes/BadRequestError.md](https://docs.typesafe.ai/sdk/javascript/api/classes/BadRequestError.md) | JavaScript | 2496 | `2463ee449a0728a535c464b7a916feec7f7cfa6c787f372682e406448783b743` |
| [sdk/javascript/api/classes/InternalServerError.md](https://docs.typesafe.ai/sdk/javascript/api/classes/InternalServerError.md) | JavaScript | 2529 | `dda08eedad85bd5516e862748dff570239b41774c53d297d29653763d17ecc07` |
| [sdk/javascript/api/classes/NotFoundError.md](https://docs.typesafe.ai/sdk/javascript/api/classes/NotFoundError.md) | JavaScript | 2492 | `3434c1a3f9198998224473bcfaf68d0e84e2831e72bf5f5ab893d0cfee67cfbf` |
| [sdk/javascript/api/classes/PermissionDeniedError.md](https://docs.typesafe.ai/sdk/javascript/api/classes/PermissionDeniedError.md) | JavaScript | 2514 | `d0c4b4c0666dfe09828238e2e3908560d0853711b5b54d6eae3654893180071b` |
| [sdk/javascript/api/classes/RateLimitError.md](https://docs.typesafe.ai/sdk/javascript/api/classes/RateLimitError.md) | JavaScript | 2692 | `11def3d900207697e5fe5163b2ccf90da0bcffacc35383a2bd69de249b43b648` |
| [sdk/javascript/api/classes/TypeSafeClient.md](https://docs.typesafe.ai/sdk/javascript/api/classes/TypeSafeClient.md) | JavaScript | 3488 | `d06e51285de022bed9deabe2fc8c4f91ddda0f9f38a9297535c7e1cd5cda79d3` |
| [sdk/javascript/api/classes/TypeSafeError.md](https://docs.typesafe.ai/sdk/javascript/api/classes/TypeSafeError.md) | JavaScript | 882 | `0ca02d89bea4a591d624dc462a6d7bb198cbf9a758772b1e8e96b62016ab93c5` |
| [sdk/javascript/api/classes/UnprocessableEntityError.md](https://docs.typesafe.ai/sdk/javascript/api/classes/UnprocessableEntityError.md) | JavaScript | 2535 | `ff95eb411c61d56ed4dfc1f26146eeaf700d20baaaadffc37130b14ccd1120c7` |
| [sdk/javascript/api/functions/choice.md](https://docs.typesafe.ai/sdk/javascript/api/functions/choice.md) | JavaScript | 890 | `3c880415afc18a8498a5484863e5eb5bfa998dc33cf1d2999bdbc5c16b12bfa8` |
| [sdk/javascript/api/functions/noul.md](https://docs.typesafe.ai/sdk/javascript/api/functions/noul.md) | JavaScript | 1365 | `f8f94ce2dbdce0aa841dfe043a5c4163980fcd72211ab9dba858ea179cd1e663` |
| [sdk/javascript/api/functions/score.md](https://docs.typesafe.ai/sdk/javascript/api/functions/score.md) | JavaScript | 885 | `0792d52afd3afc54303fce693c7c42534e57a2b8ce369cc11fb6340fb327b135` |
| [sdk/javascript/api/interfaces/ChoiceQuestion.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/ChoiceQuestion.md) | JavaScript | 947 | `82c0a35cfb782a954da2dc31e269fcc273447c7c6c9cc5d959d7c5968bfbc0a6` |
| [sdk/javascript/api/interfaces/ChoiceResponse.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/ChoiceResponse.md) | JavaScript | 1095 | `d06a957fe92af44639a97319c0cf56082ef11e243a8dfd64f093480de400d87f` |
| [sdk/javascript/api/interfaces/Logger.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/Logger.md) | JavaScript | 1148 | `e3b49455b725f3a766d0e8e3dc02243a314ccbec61f337a667238f14d6581b9d` |
| [sdk/javascript/api/interfaces/ModelCard.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/ModelCard.md) | JavaScript | 654 | `8a7bd6545efb68fda0371cf747a038ce261ebc5f44e2bae139cb2274bd3da997` |
| [sdk/javascript/api/interfaces/Models.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/Models.md) | JavaScript | 739 | `d68ed24aa95b6cfc185201da18a03b3df9b305a340a02ab157435867c83ee459` |
| [sdk/javascript/api/interfaces/NoulQuestion.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/NoulQuestion.md) | JavaScript | 1168 | `dd49aae30b34e0e5942611aa08cb9ac008b0f9270e4c9fbc5bd5eef979761385` |
| [sdk/javascript/api/interfaces/NoulResponse.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/NoulResponse.md) | JavaScript | 560 | `4c978ecf12bdd329c2468e81b1cdbe32f070c758e21f33e01c532c52e6c15b00` |
| [sdk/javascript/api/interfaces/Questions.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/Questions.md) | JavaScript | 440 | `508f221b34597ac915ae94cabfe6daa829156142fcee2b20b5c9e07c47cd0512` |
| [sdk/javascript/api/interfaces/RequestOptions.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/RequestOptions.md) | JavaScript | 1032 | `48b8d64541f9baf8b266c324df48a50ee622ec8f0cd1f7c4619cb35f29c07f88` |
| [sdk/javascript/api/interfaces/RetryPolicy.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/RetryPolicy.md) | JavaScript | 2146 | `85f6633028b04475606bba7e784fbd6db3d08ca861c5fa6e33afa243dc2b4b8b` |
| [sdk/javascript/api/interfaces/ScoreQuestion.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/ScoreQuestion.md) | JavaScript | 946 | `23960b9224205758da776d76dbcbf21975233947fed5048b09197da16913d58d` |
| [sdk/javascript/api/interfaces/ScoreResponse.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/ScoreResponse.md) | JavaScript | 1252 | `9db7752262f2e1d76df123dfc26fa97f4483e0bade858456cbd1ed6cc9678dee` |
| [sdk/javascript/api/interfaces/SystemOneRequest.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/SystemOneRequest.md) | JavaScript | 1156 | `c2f8d6a326fefca098f6d8331dd26f5721f523e16dbaf2f77f2fed81f2253ed4` |
| [sdk/javascript/api/interfaces/SystemOneRequestPayload.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/SystemOneRequestPayload.md) | JavaScript | 1405 | `50dcc14c938af2f75afdcff95a34a86e62b6395f4a0effc98e10e2d2606ce84f` |
| [sdk/javascript/api/interfaces/SystemOneResult.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/SystemOneResult.md) | JavaScript | 941 | `de54fe865040fdb8edb2440528af9a3ad02aa1b6838fd0058cde5036966a364f` |
| [sdk/javascript/api/interfaces/TypeSafeClientConfig.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/TypeSafeClientConfig.md) | JavaScript | 2314 | `60beed43998f14205e7fac512b890822f8f6f930d7039957feed517b88cf7230` |
| [sdk/javascript/api/interfaces/Usage.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/Usage.md) | JavaScript | 629 | `6c31113ae0000cbfd34b4220a8d4333c3941f654549981d89a9335444f2c31d6` |
| [sdk/javascript/api/interfaces/WithResponse.md](https://docs.typesafe.ai/sdk/javascript/api/interfaces/WithResponse.md) | JavaScript | 825 | `90ff30334b4b6f63e49cdc157f2c914817c9886043299f9d8f6c14f82b8ec306` |
| [sdk/javascript/api/type-aliases/ChoiceCriteria.md](https://docs.typesafe.ai/sdk/javascript/api/type-aliases/ChoiceCriteria.md) | JavaScript | 512 | `a511eba6b5666eee2323e476bb126e868d498d0d486c743a06143c3642dae74d` |
| [sdk/javascript/api/type-aliases/Description.md](https://docs.typesafe.ai/sdk/javascript/api/type-aliases/Description.md) | JavaScript | 435 | `92052bd2c7a1bdcd0e837c5942f506800d4e7ebc61c798a3f6199eab7e9d4910` |
| [sdk/javascript/api/type-aliases/EntryType.md](https://docs.typesafe.ai/sdk/javascript/api/type-aliases/EntryType.md) | JavaScript | 509 | `355a76ef34c00823acc4c71af7764fc2c25c9175c79cebb82cb90e6a3f4181e7` |
| [sdk/javascript/api/type-aliases/EnvVar.md](https://docs.typesafe.ai/sdk/javascript/api/type-aliases/EnvVar.md) | JavaScript | 381 | `2c979f608bbbd3223980fe5e705dd154515caf5de40cfc66956503de4a0787fb` |
| [sdk/javascript/api/type-aliases/Fetch.md](https://docs.typesafe.ai/sdk/javascript/api/type-aliases/Fetch.md) | JavaScript | 547 | `fa9814843bb1c0515d536cb494f866fff7621a5c4713335bd3c0291e0e374ac8` |
| [sdk/javascript/api/type-aliases/JsonValue.md](https://docs.typesafe.ai/sdk/javascript/api/type-aliases/JsonValue.md) | JavaScript | 478 | `d8c50dd0f6e64e149ef77c4f6ec84f646e705175a4a8fa7636b5d36c375b0d66` |
| [sdk/javascript/api/type-aliases/LogLevel.md](https://docs.typesafe.ai/sdk/javascript/api/type-aliases/LogLevel.md) | JavaScript | 440 | `df1424fcfc1ce91f694150312ff6b2935ca8ab7a81ffe9571a0aa179e3b2b227` |
| [sdk/javascript/api/type-aliases/Question.md](https://docs.typesafe.ai/sdk/javascript/api/type-aliases/Question.md) | JavaScript | 455 | `1e2bcda7a1644062945c733115e2da903a28e8d4349b7a53c8d48e64e2a3abb3` |
| [sdk/javascript/api/type-aliases/ResultFor.md](https://docs.typesafe.ai/sdk/javascript/api/type-aliases/ResultFor.md) | JavaScript | 681 | `411004d64c3a2613881de525ee6d588d4cfa1f47c3284370ddb685c133323091` |
| [sdk/javascript/api/type-aliases/ScoreCriteria.md](https://docs.typesafe.ai/sdk/javascript/api/type-aliases/ScoreCriteria.md) | JavaScript | 504 | `3599c4a136502d17c03f817cdd886cb72fa4475696b43b88abe94c6ddab5504c` |
| [sdk/javascript/api/type-aliases/ScoreLegend.md](https://docs.typesafe.ai/sdk/javascript/api/type-aliases/ScoreLegend.md) | JavaScript | 558 | `ead596841cbea63f6d3dee2ba263f2b53d84dda4dde1ca3f749a817b9f2f3bfd` |
| [sdk/javascript/api/type-aliases/ScoreOf.md](https://docs.typesafe.ai/sdk/javascript/api/type-aliases/ScoreOf.md) | JavaScript | 635 | `98098e9e3e33a943a57eb380df83db07328eb3862cc87e4a1cac7589751785c2` |
| [sdk/javascript/api/variables/ENV.md](https://docs.typesafe.ai/sdk/javascript/api/variables/ENV.md) | JavaScript | 1152 | `3e8f16fa7e6137f432a6c5ee33329038d0b469234fe38bbd3431eb095929d125` |
| [sdk/javascript/api/variables/LOG_LEVELS.md](https://docs.typesafe.ai/sdk/javascript/api/variables/LOG_LEVELS.md) | JavaScript | 429 | `8625f9eae048383a30915bc0585a494605d706d43a6bfd8574c737311b0540f2` |
| [sdk/javascript/api/variables/VERSION.md](https://docs.typesafe.ai/sdk/javascript/api/variables/VERSION.md) | JavaScript | 370 | `3c9b18c8dad4b2f0a45b62662fa3ac69d05168a3ae06af1309b80762209a99de` |
| [sdk/javascript/changelog.md](https://docs.typesafe.ai/sdk/javascript/changelog.md) | JavaScript | 621 | `6204f65e88fd44beee8a5515b4f7e6d566eb8203cac2e7838c12db1cb8890381` |
| [sdk/python.md](https://docs.typesafe.ai/sdk/python.md) | Core | 3827 | `ff4564cfcf2b577f36be5f6bb6bb0ee5f4f39306af1a39357316a54c81f92279` |
| [sdk/python/api.md](https://docs.typesafe.ai/sdk/python/api.md) | Python | 736 | `9b5fde7a25687f53e3b824736c4c94fb958065298b80aafc7c2de63d693a4a48` |
| [sdk/python/api/clients/async.md](https://docs.typesafe.ai/sdk/python/api/clients/async.md) | Python | 32688 | `4caa60c0eafbda1da734fe640ea2f43776a79d6f4a128bae3595bdf7a9029ade` |
| [sdk/python/api/clients/sync.md](https://docs.typesafe.ai/sdk/python/api/clients/sync.md) | Python | 32080 | `1524df5a9dc8bc6e0306fbdffd4b9d5ca2da49a54949276d43b6ff4a11bab338` |
| [sdk/python/api/constants.md](https://docs.typesafe.ai/sdk/python/api/constants.md) | Python | 1895 | `73d81e80043ed07af283b07b484ed2e7a309823d6e11e79f239956b8c5e741b9` |
| [sdk/python/api/exceptions.md](https://docs.typesafe.ai/sdk/python/api/exceptions.md) | Python | 7172 | `8d0ea798ce78a4e69cba889eaa9696766a09e82575b35fe79a34ce068808c7ba` |
| [sdk/python/api/retries.md](https://docs.typesafe.ai/sdk/python/api/retries.md) | Python | 15845 | `6b1137deabfac2926e08356504f02dc856892b2d061cfeedf762535c328c5ec1` |
| [sdk/python/api/types/common.md](https://docs.typesafe.ai/sdk/python/api/types/common.md) | Python | 3055 | `d93bf202cbbd2eeebb7f91af476b803400bd8ebe81b7c6013027d8b7c8c461bd` |
| [sdk/python/api/types/questions.md](https://docs.typesafe.ai/sdk/python/api/types/questions.md) | Python | 30129 | `60da0a09dc5b4115665a001344929912430f52ce381228f5a70bce8a59ee61ed` |
| [sdk/python/api/types/responses.md](https://docs.typesafe.ai/sdk/python/api/types/responses.md) | Python | 38738 | `03efd826c4334bd7260cae2fd980a9ae01a934f8714e58ea59093389a14bb6ad` |
| [sdk/python/changelog.md](https://docs.typesafe.ai/sdk/python/changelog.md) | Python | 2192 | `686ef1baf6cfe2b15c669f5cbccdf28f4e6e7ef3aafc7123f6864f868d74a821` |
| [sdk/python/usage.md](https://docs.typesafe.ai/sdk/python/usage.md) | Python | 19092 | `a6b916b9d87b3722fe6692b049480f99e0083f24b9853831ee2edd38ddc6764d` |

## Additional linked legal policies

All rows: HTTP 200; review complete. These are HTML source fingerprints.
The review is not a legal determination.

| Source | Raw bytes | SHA-256 |
|---|---:|---|
| [data-processing](https://typesafe.ai/legal/data-processing) | 190602 | `76bddbe838a4227f6836c25111e19a2c76f20133766f9241123f5ee4c5084c9b` |
| [mca](https://typesafe.ai/legal/mca) | 262487 | `1618f086e0ffcd34b3f4c350be62634e5e72da6718c80e397c5c99cbedfc7d1e` |
| [privacy-policy](https://typesafe.ai/legal/privacy-policy) | 185397 | `93012e61403f9f7f7536e94914497777f791ab51b017e08bbb5e24bc06cd31c7` |

## Refresh rule

Before implementing or spending, refresh the index, relevant contract pages,
model/SDK versions, pricing, and data terms. New pages or changed hashes require
a new review; this dated record does not assert that future documentation is
unchanged.
