# Upstream and implementation references

The exact inspected engine/API revisions are in `upstream/manifest.json`. The narrow integration modifications are verified by `tools/patch_engine.py`.

- Native engine: https://github.com/EndstoneMC/spark/tree/8958173ad40c1da9adf3254305526443c9853848
- Endstone API: https://github.com/EndstoneMC/endstone/tree/8f84d6f5b556916597ed5b6b71329b2ed3ca8fc8
- LLVM 20.1.8 installer metadata/checksum: https://api.github.com/repos/llvm/llvm-project/releases/tags/llvmorg-20.1.8
- LLVM signed apt repository: https://apt.llvm.org/
- GitHub artifact upload/download action documentation: https://github.com/actions/upload-artifact and https://github.com/actions/download-artifact
- Conan 2.29.1 package: https://pypi.org/project/conan/2.29.1/
- FastAPI testing: https://fastapi.tiangolo.com/tutorial/testing/
- Microsoft Bedrock experimental server-net reference: https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server-net/minecraft-server-net?view=minecraft-bedrock-experimental
- Docker Compose secrets: https://docs.docker.com/compose/how-tos/use-secrets/

These references establish API/build assumptions, not complete runtime qualification of this release. Native provenance and observed test results are separate from intended compatibility.
