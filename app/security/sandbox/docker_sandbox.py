"""Docker 沙箱"""

import os
import docker
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class SandboxResult:
    """沙箱执行结果"""
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    exit_code: int = 0
    execution_time: float = 0.0


class DockerSandbox:
    """Docker 沙箱执行器"""

    def __init__(self):
        self.enabled = os.environ.get("SANDBOX_ENABLED", "true").lower() == "true"
        self.image = os.environ.get("SANDBOX_IMAGE", "python:3.11-slim")
        self.memory_limit = os.environ.get("SANDBOX_MEMORY_LIMIT", "512m")
        self.cpu_limit = float(os.environ.get("SANDBOX_CPU_LIMIT", "1.0"))
        self.timeout = int(os.environ.get("SANDBOX_TIMEOUT", "300"))
        self.network_disabled = os.environ.get("SANDBOX_NETWORK_ISOLATION", "true").lower() == "true"

        self._client: Optional[docker.DockerClient] = None

    def _get_client(self) -> docker.DockerClient:
        """获取 Docker 客户端"""
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    async def execute(self, code: str, language: str = "python") -> SandboxResult:
        """在沙箱中执行代码"""
        if not self.enabled:
            return SandboxResult(success=False, error="沙箱未启用")

        if language != "python":
            return SandboxResult(success=False, error=f"不支持的语言: {language}")

        try:
            client = self._get_client()

            import time
            start_time = time.time()

            container = client.containers.run(
                self.image,
                f'python -c "{code.replace(chr(34), chr(92)+chr(34))}"',
                mem_limit=self.memory_limit,
                cpu_period=100000,
                cpu_quota=int(self.cpu_limit * 100000),
                network_disabled=self.network_disabled,
                detach=True,
                stdout=True,
                stderr=True,
            )

            try:
                result = container.wait(timeout=self.timeout)
                output = container.logs().decode("utf-8")

                execution_time = time.time() - start_time

                return SandboxResult(
                    success=result["StatusCode"] == 0,
                    output=output,
                    exit_code=result["StatusCode"],
                    execution_time=execution_time,
                )
            finally:
                container.remove(force=True)

        except Exception as e:
            return SandboxResult(success=False, error=str(e))

    async def execute_with_input(
        self,
        code: str,
        input_data: str,
        language: str = "python"
    ) -> SandboxResult:
        """在沙箱中执行带输入的代码"""
        if language != "python":
            return SandboxResult(success=False, error=f"不支持的语言: {language}")

        if not self.enabled:
            return SandboxResult(success=False, error="沙箱未启用")

        try:
            client = self._get_client()

            import time
            start_time = time.time()

            full_code = f"{code}\nprint('__INPUT_END__')\n"
            encoded_input = input_data.replace("'", "'\"'\"'")

            command = f"echo '{encoded_input}' | python -c \"{full_code}\""

            container = client.containers.run(
                self.image,
                command,
                mem_limit=self.memory_limit,
                cpu_period=100000,
                cpu_quota=int(self.cpu_limit * 100000),
                network_disabled=self.network_disabled,
                detach=True,
                stdout=True,
                stderr=True,
            )

            try:
                result = container.wait(timeout=self.timeout)
                output = container.logs().decode("utf-8")

                if "__INPUT_END__" in output:
                    output = output.split("__INPUT_END__")[0]

                execution_time = time.time() - start_time

                return SandboxResult(
                    success=result["StatusCode"] == 0,
                    output=output.strip(),
                    exit_code=result["StatusCode"],
                    execution_time=execution_time,
                )
            finally:
                container.remove(force=True)

        except Exception as e:
            return SandboxResult(success=False, error=str(e))
