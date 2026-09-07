# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import patch_engine
import publish
import package
import build_viewer
from project_files import project_files

class PatchTests(unittest.TestCase):
    def test_git_blob_hash(self):
        self.assertEqual(patch_engine.git_blob_sha(b""),"e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")
    def test_patch_and_idempotence(self):
        raw=b"before\nANCHOR\nafter\n"; sha=patch_engine.git_blob_sha(raw)
        ops=[("ANCHOR","ANCHOR\nnew API")]
        result=patch_engine.transform(raw,sha,ops)
        self.assertEqual(result,b"before\nANCHOR\nnew API\nafter\n")
        self.assertEqual(patch_engine.transform(result,sha,ops),result)
    def test_unrelated_change_rejected(self):
        with self.assertRaisesRegex(ValueError,"Unexpected source blob"):
            patch_engine.transform(b"changed",patch_engine.git_blob_sha(b"original"),[("original","patched")])
    def test_ambiguous_patch_rejected(self):
        raw=b"anchor anchor"
        with self.assertRaisesRegex(ValueError,"ambiguous"):
            patch_engine.transform(raw,patch_engine.git_blob_sha(raw),[("anchor","patched")])
    def test_malformed_utf8(self):
        with self.assertRaises(UnicodeDecodeError): patch_engine.transform(b"\xff","",[])
    def test_pins_are_consistent(self):
        manifest=json.loads((ROOT/"upstream"/"manifest.json").read_text())
        self.assertIn(patch_engine.SPARK_COMMIT,json.dumps(manifest))
        for pin in [patch_engine.SPARK_COMMIT,patch_engine.ENDSTONE_COMMIT,patch_engine.PAPI_COMMIT]:
            self.assertEqual(len(pin),40)
            int(pin,16)
    def test_engine_public_access_is_structured(self):
        self.assertIn("OniSessionSnapshot",patch_engine.API)
        self.assertIn("OniExportReceipt",patch_engine.API)
        self.assertIn("pending_outcome_",patch_engine.RECEIPT)
        self.assertNotIn("next_background_retry_ms_ = 0",patch_engine.RESUME)

class ViewerBundleTests(unittest.TestCase):
    def test_standalone_has_no_external_assets(self):
        html=build_viewer.bundle(ROOT)
        self.assertNotIn('<script src=',html)
        self.assertNotIn('<link rel="stylesheet"',html)
        self.assertNotIn("unsafe-inline",html)
        self.assertIn("connect-src 'none'",html)
    def test_assets_have_exact_hashes(self):
        html=build_viewer.bundle(ROOT)
        for name in ['styles.css','data.js','app.js']:
            self.assertIn(build_viewer.csp_hash((ROOT/'web'/name).read_text(encoding='utf-8')),html)
    def test_scripts_follow_the_document(self):
        html=build_viewer.bundle(ROOT)
        self.assertGreater(html.index('<script>'),html.index('</main>'))

class DistributionTests(unittest.TestCase):
    def test_file_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ["README.md","src/plugin.cpp",".conan2/profiles/default","build/private.txt",".env","plugins/oniprofiler/reports/private.json","web/node_modules/private.js","tools/__pycache__/bad.py"]:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text("example")
            paths={p.relative_to(root).as_posix() for p in project_files(root)}
            self.assertEqual(paths,{"README.md","src/plugin.cpp",".conan2/profiles/default"})
    def test_source_archive_excludes_builds(self):
        with tempfile.TemporaryDirectory() as directory:
            output=package.source_archive(ROOT,Path(directory)/"source.zip")
            with zipfile.ZipFile(output) as archive:
                names=archive.namelist()
                self.assertIn("OniProfiler/src/plugin.cpp",names)
                self.assertIn("OniProfiler/LICENSE",names)
                self.assertFalse(any("/build/" in n or n.endswith((".so",".dll",".pyc")) for n in names))
    def test_symlink_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/"src").mkdir();(root/"outside.h").write_text("private")
            try:(root/"src"/"bad.h").symlink_to(root/"outside.h")
            except OSError:self.skipTest("Symlinks require local permissions")
            self.assertEqual(project_files(root),[])
    def test_default_publish_is_private(self):
        args=publish.create_args("TheNINJALLO",Path("safe"),False)
        self.assertIn("--private",args);self.assertNotIn("--public",args)
        self.assertIn("TheNINJALLO/OniProfiler",args)
    def test_public_requires_explicit_flag(self):
        self.assertIn("--public",publish.create_args("TheNINJALLO",Path("safe"),True))
    def test_owner_validation(self):
        self.assertEqual(publish.owner_name("TheNINJALLO"),"TheNINJALLO")
        for invalid in ["-bad","a/b","x; echo unsafe","https://github.com/test",""]:
            with self.assertRaises(Exception):publish.owner_name(invalid)
    def test_dry_run_has_no_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/"absent"
            run=subprocess.run([sys.executable,str(ROOT/"tools"/"publish.py"),"--dry-run","--destination",str(target)],capture_output=True,text=True,check=True)
            doc=json.loads(run.stdout)
            self.assertEqual(doc["visibility"],"private")
            self.assertFalse(target.exists())
    def test_native_package_refuses_missing_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,str(ROOT/"tools"/"package.py"),"--build-dir",directory,"--platform","linux-x86_64","--output",str(Path(directory)/"out")],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn("Native binary was not built",result.stderr)

if __name__=="__main__":unittest.main()
