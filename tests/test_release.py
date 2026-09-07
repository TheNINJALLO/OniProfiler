"""Build workflow, packaging and SDK lifecycle contracts, not a native CI simulation."""
from __future__ import annotations
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'controlplane'))
from check_release import verify,checksums
from project_files import project_files
from package import validate_binary,validate_linux_glibc,source_archive
from oniprofiler_control.sdk import Instrumentor

class ReleaseTests(unittest.TestCase):
    def test_versions(self):self.assertEqual(verify(),'1.0.0')
    def test_native_platform_matrix(self):
        w=yaml.load((ROOT/'.github/workflows/build.yml').read_text(),Loader=yaml.BaseLoader)
        platforms=w['jobs']['native']['strategy']['matrix']['include']
        self.assertEqual({p['platform'] for p in platforms},{'linux-x86_64','windows-x86_64'})
        linux=next(p for p in platforms if p['platform']=='linux-x86_64')
        self.assertEqual(linux['os'],'ubuntu-22.04')
        cache=next(s for s in w['jobs']['native']['steps'] if s.get('uses','').startswith('actions/cache@'))
        self.assertIn('${{ matrix.os }}',cache['with']['key'])
        self.assertIn('${{ matrix.platform }}',cache['with']['key'])
        self.assertIn('workflow_dispatch',w['on']);self.assertIn('pull_request',w['on']);self.assertEqual(w['permissions'],{'contents':'read'})
    def test_release_is_gated_and_draft(self):
        w=yaml.load((ROOT/'.github/workflows/build.yml').read_text(),Loader=yaml.BaseLoader)
        j=w['jobs']['draft-release'];self.assertEqual(j['needs'],['checks','native'])
        run=j['steps'][-1]['run'];self.assertIn('--draft',run);self.assertIn('--verify-tag',run)
        self.assertIn('if [[ "$RELEASE_TAG" == *-* ]]',run)
        self.assertIn('release_flags+=(--prerelease)',run)
        downloads={s.get('with',{}).get('name') for s in j['steps'] if s.get('uses','').startswith('actions/download-artifact@')}
        self.assertEqual(downloads,{'OniProfiler-application','OniProfiler-linux-x86_64','OniProfiler-windows-x86_64'})
        self.assertFalse(any('pattern' in s.get('with',{}) for s in j['steps']))
        self.assertNotIn('pull_request_target',w['on'])
    def test_native_checks_and_artifacts(self):
        w=yaml.load((ROOT/'.github/workflows/build.yml').read_text(),Loader=yaml.BaseLoader)
        steps=w['jobs']['native']['steps'];text='\n'.join(s.get('run','') for s in steps)
        self.assertIn('cmake --build --preset conan-relwithdebinfo',text);self.assertIn('ctest --test-dir build/RelWithDebInfo',text)
        self.assertIn('--build-dir build/RelWithDebInfo',text)
        binary=[s for s in steps if s.get('with',{}).get('archive')=='false'][0]
        self.assertEqual(binary['with']['if-no-files-found'],'error')
    def test_repository_conan_profile_is_selected(self):
        self.assertEqual((ROOT/'.conanrc').read_text().strip(),'conan_home=./.conan2')
        self.assertTrue((ROOT/'.conan2/profiles/default').is_file())
    def test_zip_importer_cannot_overwrite_normal_pushes(self):
        workflow=yaml.load((ROOT/'.github/workflows/github_workflows_extract-zip.yml').read_text(),Loader=yaml.BaseLoader)
        self.assertEqual(workflow['on'],{'workflow_dispatch':{}})
    def test_toolchain_verification(self):
        ps=(ROOT/'tools/ci/install-llvm-windows.ps1').read_text();sh=(ROOT/'tools/ci/install-llvm-linux.sh').read_text()
        self.assertIn('3197846a2b19063687dd56e93e34cd941e3548d907f23a6131571321bdf9fe7b',ps)
        self.assertLess(ps.index('Get-FileHash'),ps.index('Start-Process'))
        self.assertIn('6084F3CF814B57C1CF12EFD515CF4D18AF4F7421',sh);self.assertIn('signed-by=',sh)
    def test_combined_source_files_included(self):
        names={p.relative_to(ROOT).as_posix() for p in project_files(ROOT)}
        self.assertTrue({'INSTALL.md','controlplane/oniprofiler_control/server.py','controlplane/oniprofiler_control/static/app.js','controlplane/pyproject.toml','integrations/runtime-sdk.mjs','deploy/Dockerfile','deploy/Caddyfile','deploy/agent.example.toml','tools/ci/install-llvm-windows.ps1','.github/workflows/build.yml','VERSION','controlplane/LICENSE'}<=names)
        self.assertIn('"INSTALL.md"',(ROOT/'tools/package.py').read_text())
    def test_private_and_build_files_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ['deploy/agent.toml','deploy/secrets/secret.json','controlplane/build/bad.py','controlplane/x.egg-info/PKG-INFO','controlplane/credentials.json','deploy/.env','controlplane/__pycache__/x.py','deploy/agent.example.toml']:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('x')
            self.assertEqual([p.relative_to(root).as_posix() for p in project_files(root)],['deploy/agent.example.toml'])
    def test_native_magic_and_architecture(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fixture';data=bytearray(1024);data[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',data,16,3);struct.pack_into('<H',data,18,62);p.write_bytes(data)
            validate_binary(p,'linux-x86_64')
            struct.pack_into('<H',data,18,183);p.write_bytes(data)
            with self.assertRaises(ValueError):validate_binary(p,'linux-x86_64')
            data=bytearray(1024);data[:2]=b'MZ';struct.pack_into('<I',data,60,128);data[128:132]=b'PE\0\0';struct.pack_into('<H',data,132,0x8664);struct.pack_into('<H',data,150,0x2000);p.write_bytes(data)
            validate_binary(p,'windows-x86_64')
            data[128]=0;p.write_bytes(data)
            with self.assertRaises(ValueError):validate_binary(p,'windows-x86_64')
    def test_linux_glibc_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'plugin.so';p.write_bytes(b'ELF GLIBC_2.2.5 GLIBC_2.35')
            validate_linux_glibc(p)
            p.write_bytes(b'ELF GLIBC_2.38')
            with self.assertRaises(ValueError):validate_linux_glibc(p)
    def test_checksum_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'a.txt').write_bytes(b'abc');out=checksums(root)
            self.assertIn('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',out.read_text())
            self.assertEqual(checksums(root).read_text().count('a.txt'),1)
    def test_exporter_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            sdk=Instrumentor('TestPlugin',Path(d));sdk.start_exporter(5)
            with self.assertRaises(RuntimeError):sdk.start_exporter(5)
            self.assertTrue(sdk.stop_exporter());sdk.start_exporter(5);self.assertTrue(sdk.stop_exporter())
    def test_exporter_validation(self):
        with self.assertRaises(ValueError):Instrumentor('TestPlugin').start_exporter()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):Instrumentor('TestPlugin',Path(d)).start_exporter(0.1)
    def test_no_secrets_in_deployment_defaults(self):
        compose=yaml.safe_load((ROOT/'deploy/compose.yml').read_text());dashboard=compose['services']['dashboard']
        self.assertNotIn('ports',dashboard);self.assertTrue(dashboard['read_only'])
        agent=(ROOT/'deploy/agent.example.toml').read_text();self.assertIn('sync_native_profiles = false',agent)
        self.assertIn('token_file = ',agent);self.assertNotIn('password',agent)
class LauncherTests(unittest.TestCase):
    def test_finished_process_is_untouched(self):
        from unittest.mock import Mock
        from oniprofiler_control.launcher import request_stop
        process=Mock();process.poll.return_value=0
        request_stop(process);process.send_signal.assert_not_called();process.terminate.assert_not_called()
    def test_windows_uses_console_break_not_terminate(self):
        from unittest.mock import Mock,patch
        from oniprofiler_control.launcher import request_stop
        process=Mock();process.poll.return_value=None
        with patch("oniprofiler_control.launcher.os.name","nt"),patch("oniprofiler_control.launcher.signal.CTRL_BREAK_EVENT",1,create=True):
            request_stop(process)
        process.send_signal.assert_called_once_with(1);process.terminate.assert_not_called();process.kill.assert_not_called()
    def test_posix_uses_graceful_group_signal(self):
        from unittest.mock import Mock,patch
        from oniprofiler_control.launcher import request_stop
        import signal
        process=Mock();process.poll.return_value=None;process.pid=12345
        with patch("oniprofiler_control.launcher.os.name","posix"),patch("oniprofiler_control.launcher.os.killpg",create=True) as send:
            request_stop(process);send.assert_called_once_with(12345,signal.SIGTERM)
        process.terminate.assert_not_called();process.kill.assert_not_called()
if __name__=='__main__':unittest.main()
