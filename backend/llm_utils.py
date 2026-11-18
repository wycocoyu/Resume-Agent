"""
LLM 调用工具函数
包含重试机制、超时处理等
"""

import time
from typing import Callable, Any
from functools import wraps

try:
    from backend.services.ai_guard import is_non_retryable_ai_error
except ImportError:
    from services.ai_guard import is_non_retryable_ai_error


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0
):
    """
    带指数退避的重试装饰器
    
    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟时间（秒）
        backoff_factor: 退避因子
    
    Example:
        @retry_with_backoff(max_retries=3)
        def call_api():
            # API 调用代码
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (TimeoutError, ConnectionError, Exception) as e:
                    if is_non_retryable_ai_error(e):
                        raise
                    last_exception = e
                    
                    if attempt < max_retries - 1:
                        print(f"[重试] 第 {attempt + 1}/{max_retries} 次失败: {str(e)}")
                        print(f"[重试] 等待 {delay} 秒后重试...")
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        print(f"[重试] 已达最大重试次数 {max_retries}，放弃")
            
            """
            所有重试都失败，抛出最后一个异常
            """
            raise last_exception
        
        return wrapper
    return decorator


def timeout_handler(timeout_seconds: int = 30):
    """
    超时处理装饰器
    
    Args:
        timeout_seconds: 超时时间（秒）
    
    Note:
        这是一个简单的超时处理，实际超时由底层 HTTP 客户端控制
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            """
            这里只是记录超时设置
            实际超时由 requests 或 httpx 的 timeout 参数控制
            """
            return func(*args, **kwargs)
        return wrapper
    return decorator


"""
组合装饰器：重试 + 超时
"""
def safe_llm_call(max_retries: int = 3, timeout: int = 30):
    """
    安全的 LLM 调用装饰器
    组合了重试和超时处理
    
    Example:
        @safe_llm_call(max_retries=3, timeout=30)
        def call_zhipu(prompt):
            # 调用代码
            pass
    """
    def decorator(func: Callable) -> Callable:
        @retry_with_backoff(max_retries=max_retries)
        @timeout_handler(timeout_seconds=timeout)
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            return func(*args, **kwargs)
        return wrapper
    return decorator
