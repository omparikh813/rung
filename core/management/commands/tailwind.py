"""Build static/css/output.css with the Tailwind standalone CLI (no Node)."""

import platform
import stat
import subprocess

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

RELEASES = "https://github.com/tailwindlabs/tailwindcss/releases/latest/download/"
BINARIES = {
    ("Linux", "x86_64"): "tailwindcss-linux-x64",
    ("Linux", "aarch64"): "tailwindcss-linux-arm64",
    ("Darwin", "x86_64"): "tailwindcss-macos-x64",
    ("Darwin", "arm64"): "tailwindcss-macos-arm64",
    ("Windows", "AMD64"): "tailwindcss-windows-x64.exe",
}


class Command(BaseCommand):
    help = "Build static/css/output.css with the Tailwind standalone CLI."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true", help="Rebuild when templates change.")

    def handle(self, *args, **options):
        name = BINARIES.get((platform.system(), platform.machine()))
        if not name:
            raise CommandError(f"No Tailwind CLI for {platform.system()} {platform.machine()}.")
        binary = settings.BASE_DIR / ".tools" / name
        if not binary.exists():
            self.stdout.write(f"Downloading {name} ...")
            binary.parent.mkdir(exist_ok=True)
            response = httpx.get(RELEASES + name, follow_redirects=True, timeout=120)
            response.raise_for_status()
            binary.write_bytes(response.content)
            binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        css = settings.BASE_DIR / "static" / "css"
        command = [str(binary), "-i", str(css / "input.css"), "-o", str(css / "output.css"), "--minify"]
        if options["watch"]:
            command.append("--watch")
        subprocess.run(command, cwd=settings.BASE_DIR, check=True)
        self.stdout.write(self.style.SUCCESS("Built static/css/output.css"))
