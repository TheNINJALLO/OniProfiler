# SPDX-License-Identifier: GPL-3.0-only
# Native dependency versions match the inspected EndstoneMC/spark recipe.
from conan import ConanFile
from conan.tools.cmake import cmake_layout

class OniProfilerRecipe(ConanFile):
    name = "oniprofiler"
    version = "1.0.1"
    settings = "os", "compiler", "build_type", "arch"
    generators = "CMakeToolchain", "CMakeDeps"

    def layout(self):
        cmake_layout(self)

    def requirements(self):
        for dependency in ("cpptrace/1.0.4", "concurrentqueue/1.0.4", "zlib/1.3.1",
                           "expected-lite/0.9.0", "libcurl/8.21.0", "tomlplusplus/3.0.1"):
            self.requires(dependency)
        if self.settings.os != "Windows":
            self.requires("openssl/3.6.3")

    def generate(self):
        """Keep the licenses of linked Conan packages with the release artifacts."""
        import json
        from pathlib import Path
        from conan.tools.files import copy
        destination=Path(self.build_folder)/"third-party-licenses"
        destination.mkdir(parents=True,exist_ok=True)
        manifest=[]
        for dependency in self.dependencies.host.values():
            reference=str(dependency.ref)
            name=str(dependency.ref.name)+"-"+str(dependency.ref.version)
            folder=Path(dependency.package_folder) if dependency.package_folder else None
            license_folder=folder/"licenses" if folder else None
            copied=bool(license_folder and license_folder.is_dir())
            if copied:
                copy(self,"*",src=str(license_folder),dst=str(destination/name))
            manifest.append({"reference":reference,"license":str(getattr(dependency,"license","See included license files")),"license_files_copied":copied})
        (destination/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
