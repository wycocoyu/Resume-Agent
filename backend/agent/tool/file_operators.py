"""Local file operations used by the resume editor tool."""

import asyncio
from pathlib import Path
from typing import Optional, Protocol, Tuple, Union, runtime_checkable

from backend.agent.exceptions import ToolError

PathLike = Union[str, Path]


@runtime_checkable
class FileOperator(Protocol):
    async def read_file(self, path: PathLike) -> str: ...
    async def write_file(self, path: PathLike, content: str) -> None: ...
    async def is_directory(self, path: PathLike) -> bool: ...
    async def exists(self, path: PathLike) -> bool: ...
    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]: ...


class LocalFileOperator(FileOperator):
    """Read and mutate files on the application host only."""

    encoding = "utf-8"

    async def read_file(self, path: PathLike) -> str:
        try:
            return Path(path).read_text(encoding=self.encoding)
        except OSError as exc:
            raise ToolError(f"Failed to read {path}: {exc}") from exc

    async def write_file(self, path: PathLike, content: str) -> None:
        try:
            Path(path).write_text(content, encoding=self.encoding)
        except OSError as exc:
            raise ToolError(f"Failed to write to {path}: {exc}") from exc

    async def is_directory(self, path: PathLike) -> bool:
        return Path(path).is_dir()

    async def exists(self, path: PathLike) -> bool:
        return Path(path).exists()

    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            raise TimeoutError(
                f"Command '{cmd}' timed out after {timeout} seconds"
            ) from exc
        return process.returncode or 0, stdout.decode(), stderr.decode()
