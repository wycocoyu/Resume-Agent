"""
ASR (Automatic Speech Recognition) 服务
使用 Vosk API（免费方案）
"""

import io
import logging
import os
from typing import Optional, Literal, List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from backend.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/asr", tags=["ASR"])


class ASRConfig(BaseModel):
    """ASR 配置"""
    language: str = Field(default="zh-CN", description="语言代码")
    model: str = Field(default="vad", description="模型名称")
    sample_rate: int = Field(default=16000, description="采样率")


class ASRResponse(BaseModel):
    """ASR 响应"""
    success: bool
    text: str
    confidence: float
    duration_ms: int


@router.post("/recognize", response_model=ASRResponse)
async def recognize_speech(
    audio_file: UploadFile = File(..., description="音频文件（wav, mp3, opus）"),
    config: ASRConfig = ASRConfig(),
):
    """
    识别语音文件

    Args:
        audio_file: 音频文件（支持 wav, mp3, opus, ogg）
        config: ASR 配置

    Returns:
        识别结果
    """
    try:
        asr_url = os.getenv("ASR_API_URL", "").strip()
        if not asr_url:
            raise HTTPException(status_code=503, detail="ASR 语音识别服务未配置")

        import aiohttp

        # 读取音频文件
        audio_data = await audio_file.read()
        audio_size = len(audio_data)

        logger.info(f"Received audio: {audio_size} bytes, format: {audio_file.content_type}")

        # 检查文件大小（限制 25MB）
        MAX_AUDIO_SIZE = 25 * 1024 * 1024
        if audio_size > MAX_AUDIO_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Audio file too large. Max size: {MAX_AUDIO_SIZE} bytes"
            )

        async with aiohttp.ClientSession() as session:
            # 准备请求数据
            data = aiohttp.FormData()
            data.add_field('model', config.model)
            data.add_field('language', config.language)

            # 添加音频文件
            data.add_field(
                "file",
                audio_data,
                filename=audio_file.filename or "audio.wav",
                content_type=audio_file.content_type or "application/octet-stream",
            )

            # 发送请求
            headers = {
                "User-Agent": "CocoCV/3.12.1"
            }

            async with session.post(asr_url, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    result = await response.json()

                    # 解析响应
                    text = result.get('text', '')
                    confidence = result.get('confidence', 0.0)

                    logger.info(f"ASR success: text='{text[:50]}...', confidence={confidence}")

                    return ASRResponse(
                        success=True,
                        text=text,
                        confidence=confidence,
                        duration_ms=0  # Vosk 不返回时长
                    )
                else:
                    error_text = await response.text()
                    logger.error(f"ASR failed: {response.status} - {error_text}")
                    raise HTTPException(status_code=500, detail="Speech recognition failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ASR error: {e}")
        raise HTTPException(status_code=500, detail=f"Speech recognition error: {str(e)}")


class StreamASRConfig(BaseModel):
    """流式 ASR 配置"""
    language: str = Field(default="zh-CN", description="语言代码")
    sample_rate: int = Field(default=16000, description="采样率")
    chunk_size: int = Field(default=2000, description="块大小（ms）")


@router.websocket("/ws/stream")
async def websocket_stream_asr(websocket: WebSocket):
    """
    WebSocket 端点：流式语音识别

    流程：
    1. 客户端连接 WebSocket
    2. 客户端开始发送音频块
    3. 服务端识别每一块
    4. 累积识别结果
    5. 检测静音/活动状态
    6. 返回部分结果
    """
    # 配置
    language = "zh-CN"
    sample_rate = 16000
    accumulated_text = ""
    is_speaking = False
    silence_count = 0
    MAX_SILENCE_CHUNKS = 10  # 10 个块（1秒）没有音频则认为停止

    try:
        await websocket.accept()
        logger.info(f"WebSocket ASR connection established")

        while True:
            try:
                # 接收音频块（二进制）
                chunk = await websocket.receive_bytes()

                if not chunk:
                    logger.debug("Received empty chunk, client might be done")
                    # 检查是否需要返回累积文本
                    if accumulated_text:
                        await websocket.send_json({
                            "type": "final",
                            "text": accumulated_text.strip(),
                        })
                        accumulated_text = ""
                    break

                # 模拟处理（实际应该调用 ASR API）
                # 这里简化处理，每 5 个块识别一次
                # 在生产环境中应该：
                # 1. 缓冲音频块
                # 2. 当达到 chunk_size 时调用 ASR API
                # 3. 返回部分结果

                await websocket.send_json({
                    "type": "ack",
                    "received": len(chunk),
                })

            except WebSocketDisconnect:
                logger.info("WebSocket ASR client disconnected")
                break

    except Exception as e:
        logger.error(f"WebSocket ASR error: {e}")
        await websocket.close()


@router.get("/health")
async def health_check():
    """ASR 健康检查"""
    return {
        "success": True,
        "status": "healthy",
        "service": "vosk-asr",
    }
