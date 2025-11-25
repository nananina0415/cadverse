# server_data_models.py
# 서버 관련 데이터 모델 및 타입 정의

import json
from dataclasses import dataclass
from typing import Any, Dict
from utils.read_write_buffer import ReadWriteBuffer


@dataclass
class ServerConfig:
    """서버 설정"""
    host: str = "0.0.0.0"
    port: int = 8000
    resources_dir: str = "./resources"

    @classmethod
    def fromJson(cls, jsonPath: str) -> 'ServerConfig':
        """JSON 파일에서 설정 로드"""
        with open(jsonPath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls(**data)

    def toDict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            'host': self.host,
            'port': self.port,
            'resources_dir': self.resources_dir
        }


@dataclass
class UserInput:
    """사용자 입력 데이터"""
    data: Dict[str, Any]


@dataclass
class Server:
    """
    서버 상태 컨테이너
    - config: 서버 설정
    - userInput: 사용자 입력 버퍼
    """
    config: ServerConfig
    userInput: ReadWriteBuffer[UserInput]
