"""Mock 被测智能体服务入口。

启动：cd dev/mock && python -m uvicorn app:app --host 0.0.0.0 --port 8100
或：  cd dev/mock && python main.py
"""
import uvicorn

from .config import mock_settings


def run() -> None:
    uvicorn.run(
        "app:app",
        host=mock_settings.MOCK_HOST,
        port=mock_settings.MOCK_PORT,
        reload=False,
    )


if __name__ == "__main__":
    run()
