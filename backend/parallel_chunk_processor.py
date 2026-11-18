"""
并行分块处理器
使用异步并发处理简历分块，大幅提升处理速度
"""

import asyncio
import aiohttp
import time
import re
import sys
from typing import List, Dict, Any, Optional
import json as _json
from concurrent.futures import ThreadPoolExecutor
import functools

# 导入现有的同步函数（兼容多种运行方式）
# 确保 backend 目录在 sys.path 中
import sys
from pathlib import Path

current_file = Path(__file__).resolve()
backend_dir = current_file.parent
project_root = backend_dir.parent

# 确保项目根目录和 backend 目录都在 sys.path 中
for p in [project_root, backend_dir]:
    p_str = str(p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)

# 统一导入方式：优先使用绝对导入（backend.xxx），失败则使用相对导入
try:
    # 方式1：作为 backend 包的子模块导入（适用于 uvicorn backend.main:app）
    from backend.llm import call_llm
    from backend.chunk_processor import split_resume_text, merge_resume_chunks
    from backend.config.parallel_config import get_parallel_config
    from backend.core.logger import get_logger, write_llm_debug
    from backend.resume_text_preprocessor import normalize_pasted_resume_text
    from backend.resume_parse_rules import RESUME_PARSE_EXTRA_RULES
    from backend.services.ai_guard import AiGuardError
except ImportError:
    try:
        # 方式2：作为顶层模块导入（适用于 backend 目录已在 sys.path）
        from llm import call_llm
        from chunk_processor import split_resume_text, merge_resume_chunks
        from config.parallel_config import get_parallel_config
        from core.logger import get_logger, write_llm_debug
        from resume_text_preprocessor import normalize_pasted_resume_text
        from resume_parse_rules import RESUME_PARSE_EXTRA_RULES
        from services.ai_guard import AiGuardError
    except ImportError as e:
        # 如果都失败，抛出错误
        raise ImportError(f"无法导入必要的模块：{e}")

logger = get_logger(__name__)


def clean_llm_response(raw: str) -> str:
    """清理 LLM 返回的内容"""
    cleaned = re.sub(r'<\|begin_of_box\|>', '', raw)
    cleaned = re.sub(r'<\|end_of_box\|>', '', cleaned)
    cleaned = re.sub(r'```json\s*', '', cleaned)
    cleaned = re.sub(r'```\s*', '', cleaned)
    return cleaned.strip()


def parse_json_response(cleaned: str) -> Dict:
    """解析 JSON 响应"""
    try:
        return _json.loads(cleaned)
    except Exception:
        # 尝试提取 JSON 部分
        if cleaned.startswith('['):
            start = cleaned.find('[')
            end = cleaned.rfind(']')
        else:
            start = cleaned.find('{')
            end = cleaned.rfind('}')
        
        if start != -1 and end != -1 and end > start:
            return _json.loads(cleaned[start:end+1])
        raise


class ParallelChunkProcessor:
    """并行分块处理器"""

    def __init__(self, provider: str = None, max_concurrent: int = None):
        """
        初始化并行处理器

        Args:
            provider: AI提供商，用于获取特定配置
            max_concurrent: 手动指定最大并发数，覆盖配置
        """
        config = get_parallel_config(provider)

        self.max_concurrent = max_concurrent or config.get("max_concurrent", 3)
        self.provider = provider
        self.config = config
        self.executor = ThreadPoolExecutor(max_workers=self.max_concurrent)

    async def process_chunk_async(self, provider: str, chunk: Dict[str, str],
                                  schema_desc: str, chunk_index: int, total_chunks: int) -> Dict[str, Any]:
        """
        异步处理单个分块

        Args:
            provider: AI提供商
            chunk: 分块数据
            schema_desc: Schema描述
            chunk_index: 分块索引
            total_chunks: 总分块数

        Returns:
            解析后的数据
        """
        start_time = time.time()

        # 构建提示词（保持与原版一致）
        chunk_prompt = f"""从简历文本片段提取信息,只输出JSON(不要markdown,无数据的字段用空数组[]):

解析规则：
1. 技能描述：如果有多行以"-"开头的技能描述，每行应该作为一个独立的技能项，格式为{{"category":"","details":"该行的完整内容(去掉开头的破折号)"}}
2. 项目经历（极其重要，必须严格遵守）：
   - 只有"### xxx"或"## xxx"开头的才是项目标题
   - 项目描述段落（从项目标题后、第一个"- **"之前的完整段落）放入"description"字段
   - 技术栈信息（如"技术栈：SpringBoot MySQL..."）附加到 description 字段末尾
   - 以"- **标题**：描述"格式开头的行是项目的功能亮点，每行一个，放入该项目的"highlights"字符串数组
   - highlights数组中的每一项保持原格式，包括**加粗标记**
   - 绝对不要把功能亮点合并到description中！

正确示例：
输入文本：
### RAG 知识库助手
基于私有知识库的 RAG 对话平台。
技术栈：SpringBoot MySQL Redis

- **上下文截断**：解决截断问题
- **文档解析**：多格式解析

输出：
{{
  "projects": [
    {{
      "title": "RAG 知识库助手",
      "description": "基于私有知识库的 RAG 对话平台。技术栈：SpringBoot MySQL Redis",
      "highlights": [
        "**上下文截断**：解决截断问题",
        "**文档解析**：多格式解析"
      ]
    }}
  ]
}}

注意：highlights数组中每项不要开头的"- "符号，前端会用无序列表渲染！

片段内容({chunk['section']}):
{chunk['content']}
{schema_desc}"""

        try:
            # 获取超时配置
            timeout = self.config.get("request_timeout", 15)
            
            # 使用线程池执行同步的 call_llm 函数，并添加异步超时控制
            loop = asyncio.get_event_loop()
            raw = await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    functools.partial(call_llm, provider, chunk_prompt)
                ),
                timeout=timeout
            )

            # 检查 raw 是否为空
            if not raw:
                raise Exception(f"API 返回空内容 (raw is None or empty)")

            # 清理和解析响应（这里也可以优化为异步）
            cleaned = await loop.run_in_executor(
                self.executor,
                clean_llm_response,
                raw
            )
            
            # 检查 cleaned 是否为空
            if not cleaned:
                raise Exception(f"清理后的内容为空。原始内容: {raw[:200] if raw else 'None'}")

            chunk_data = await loop.run_in_executor(
                self.executor,
                parse_json_response,
                cleaned
            )

            elapsed = time.time() - start_time
            print(f"[并行处理] 第 {chunk_index+1}/{total_chunks} 块完成，耗时: {elapsed:.2f}秒", file=sys.stderr, flush=True)
            logger.info(f"第 {chunk_index+1}/{total_chunks} 块完成，耗时: {elapsed:.2f}秒")

            return {
                "index": chunk_index,
                "data": chunk_data,
                "success": True,
                "elapsed": elapsed
            }

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            timeout = self.config.get("request_timeout", 15)
            error_msg = f"请求超时（超过 {timeout} 秒）"
            logger.error(f"第 {chunk_index+1}/{total_chunks} 块失败: {error_msg}, 耗时: {elapsed:.2f}秒")
            return {
                "index": chunk_index,
                "data": None,
                "success": False,
                "error": error_msg,
                "elapsed": elapsed
            }
        except AiGuardError:
            raise
        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = str(e) if str(e) else f"未知错误: {type(e).__name__}"
            logger.error(f"第 {chunk_index+1}/{total_chunks} 块失败: {error_msg}, 耗时: {elapsed:.2f}秒")

            write_llm_debug(f"Chunk {chunk_index+1} Error: {error_msg}")

            return {
                "index": chunk_index,
                "data": None,
                "success": False,
                "error": error_msg,
                "elapsed": elapsed
            }

    async def process_chunks_parallel(self, provider: str, chunks: List[Dict[str, str]],
                                     schema_desc: str) -> List[Dict[str, Any]]:
        """
        并行处理所有分块

        Args:
            provider: AI提供商
            chunks: 分块列表
            schema_desc: Schema描述

        Returns:
            解析结果列表
        """
        print("========== [并行处理] 开始并行处理 ==========", file=sys.stderr, flush=True)
        print(f"[并行处理] 分块数量: {len(chunks)}", file=sys.stderr, flush=True)
        print(f"[并行处理] 并发数: {self.max_concurrent}", file=sys.stderr, flush=True)
        print(f"[并行处理] 预计轮次: {(len(chunks) + self.max_concurrent - 1) // self.max_concurrent}", file=sys.stderr, flush=True)
        logger.info("========== 开始并行处理 ==========")
        logger.info(f"分块数量: {len(chunks)}")
        logger.info(f"并发数: {self.max_concurrent}")
        logger.info(f"预计轮次: {(len(chunks) + self.max_concurrent - 1) // self.max_concurrent}")
        start_time = time.time()

        # 创建任务队列
        tasks = []
        for i, chunk in enumerate(chunks):
            task = self.process_chunk_async(
                provider, chunk, schema_desc, i, len(chunks)
            )
            tasks.append(task)

        # 使用信号量控制并发数
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def controlled_task(task):
            async with semaphore:
                return await task

        # 执行所有任务
        controlled_tasks = [controlled_task(task) for task in tasks]
        results = await asyncio.gather(*controlled_tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, AiGuardError):
                raise r

        # 统计结果（处理异常情况）
        total_time = time.time() - start_time
        successful = [r for r in results if isinstance(r, dict) and r.get('success')]
        failed = [r for r in results if isinstance(r, dict) and not r.get('success')]
        exceptions = [r for r in results if not isinstance(r, dict)]

        print("========== [并行处理] 并行处理完成 ==========", file=sys.stderr, flush=True)
        print(f"[并行处理] 总耗时: {total_time:.2f}秒", file=sys.stderr, flush=True)
        print(f"[并行处理] 成功: {len(successful)}/{len(chunks)}", file=sys.stderr, flush=True)
        print(f"[并行处理] 失败: {len(failed)}/{len(chunks)}", file=sys.stderr, flush=True)
        logger.info("========== 并行处理完成 ==========")
        logger.info(f"总耗时: {total_time:.2f}秒")
        logger.info(f"成功: {len(successful)}/{len(chunks)}")
        logger.info(f"失败: {len(failed)}/{len(chunks)}")
        if exceptions:
            logger.warning(f"⚠️  异常: {len(exceptions)}/{len(chunks)}")
            for i, exc in enumerate(exceptions, 1):
                logger.warning(f"  异常 {i}: {type(exc).__name__}: {str(exc)[:100]}")
        if failed:
            logger.warning("⚠️  失败详情:")
            for f in failed:
                logger.warning(f"  块 {f.get('index', '?')+1}: {f.get('error', '未知错误')[:100]}")
        if successful:
            avg_time = sum(r['elapsed'] for r in successful) / len(successful)
            max_time = max(r['elapsed'] for r in successful)
            min_time = min(r['elapsed'] for r in successful)
            logger.info(f"平均单块耗时: {avg_time:.2f}秒 (最快: {min_time:.2f}秒, 最慢: {max_time:.2f}秒)")
            if total_time > 0:
                speedup = (len(chunks) * avg_time / total_time) if total_time > 0 else 0
                logger.info(f"并行效率提升: {speedup:.1f}x")
                if speedup < 1.5:
                    logger.warning("⚠️  并行效果不佳，可能被限流或网络延迟")
        if len(successful) < len(chunks):
            logger.warning("⚠️  警告: 部分分块处理失败，可能影响结果完整性")

        # 返回按索引排序的数据（只返回成功的结果）
        valid_results = [r for r in results if isinstance(r, dict) and r.get('data')]
        sorted_results = sorted(valid_results, key=lambda x: x.get('index', 0))
        return [r['data'] for r in sorted_results if r.get('data')]

    def close(self):
        """关闭线程池"""
        self.executor.shutdown(wait=True)


# 便捷函数：替换原有的串行处理
async def parse_resume_text_parallel(text: str, provider: str,
                                     chunk_threshold: int = None,
                                     max_chunk_size: int = 300,
                                     max_concurrent: int = None,
                                     model: str = None) -> Dict[str, Any]:
    """
    并行解析简历文本（保持与原函数签名兼容）

    Args:
        text: 简历文本
        provider: AI提供商
        chunk_threshold: 分块阈值
        max_chunk_size: 最大分块大小
        max_concurrent: 最大并发数
        model: 可选，指定具体模型（如 deepseek-v3.2, deepseek-reasoner）

    Returns:
        解析后的简历数据
    """
    text = normalize_pasted_resume_text(text)

    # Schema定义（保持与原版一致）
    schema_desc = """格式:{"name":"姓名","contact":{"phone":"电话","email":"邮箱"},"objective":"求职意向","education":[{"title":"学校","subtitle":"专业","degree":"学位(本科/硕士/博士)","date":"时间","details":["荣誉"]}],"internships":[{"title":"公司","subtitle":"职位","date":"时间","highlights":["工作内容"]}],"projects":[{"title":"项目名","subtitle":"角色","date":"时间","description":"项目描述(可选)","highlights":["描述"]}],"openSource":[{"title":"开源项目","subtitle":"角色/描述","date":"时间(格式: 2023.01-2023.12 或 2023.01-至今)","items":["贡献描述"],"repoUrl":"仓库链接"}],"skills":[{"category":"类别","details":"技能描述"}],"awards":["奖项"]}

重要说明：
1. 技能描述：如果原文中技能描述部分有多行，每行以"-"开头，应该将每一行作为一个独立的技能项，格式为{"category":"","details":"该行的完整内容(去掉开头的破折号)"}
2. 项目经历（极其重要，必须严格遵守）：
   - "### xxx"或"## xxx"开头的是项目标题；若无 markdown 标题，则「项目经历：」后第一行是项目名
   - 项目描述段落（从项目标题后、技术栈前的完整段落）必须放入"description"字段
   - 技术栈信息（如"技术栈：SpringBoot MySQL..."）应该附加到 description 字段末尾
   - "- **标题**：描述"或 "- 架构设计：描述"格式是项目的功能亮点，必须放入该项目的"highlights"数组，绝不能作为独立项目！
   - highlights数组中的每一项应该保持原文格式，包括加粗标记
   - 如果只看到功能亮点（"- **xxx**：描述"）而没有项目标题，将这些放入highlights数组，title留空，系统会自动合并
""" + RESUME_PARSE_EXTRA_RULES

    # 获取配置
    config = get_parallel_config(provider)
    chunk_threshold = chunk_threshold or config.get("chunk_threshold", 800)

    # 检查是否需要分块
    if len(text) <= chunk_threshold:
        # 短文本直接处理（使用异步方式）
        prompt = f"""从简历文本提取信息,只输出JSON(不要markdown,无数据的字段用空数组[]):

解析规则：
1. 技能描述：如果有多行以"-"开头的技能描述，每行应该作为一个独立的技能项，格式为{{"category":"","details":"该行的完整内容(去掉开头的破折号)"}}
2. 项目经历（极其重要，必须严格遵守）：
   - 只有"### xxx"或"## xxx"开头的才是项目标题
   - 项目描述段落（从项目标题后、第一个"- **"之前的完整段落）放入"description"字段
   - 技术栈信息（如"技术栈：SpringBoot MySQL..."）附加到 description 字段末尾
   - 以"- **标题**：描述"格式开头的行是项目的功能亮点，每行一个，放入该项目的"highlights"字符串数组
   - highlights数组中的每一项保持原格式，包括**加粗标记**
   - 绝对不要把功能亮点合并到description中！

正确示例：
输入文本：
### RAG 知识库助手
基于私有知识库的 RAG 对话平台。
技术栈：SpringBoot MySQL Redis

- **上下文截断**：解决截断问题
- **文档解析**：多格式解析

输出：
{{
  "projects": [
    {{
      "title": "RAG 知识库助手",
      "description": "基于私有知识库的 RAG 对话平台。技术栈：SpringBoot MySQL Redis",
      "highlights": [
        "**上下文截断**：解决截断问题",
        "**文档解析**：多格式解析"
      ]
    }}
  ]
}}

注意：highlights数组中每项不要开头的"- "符号，前端会用无序列表渲染！

简历文本:
{text}
{schema_desc}"""

        loop = asyncio.get_event_loop()
        # 使用线程池执行同步的 call_llm 函数
        raw = await loop.run_in_executor(
            None,  # 使用默认线程池
            functools.partial(call_llm, provider, prompt)
        )
        cleaned = clean_llm_response(raw)
        result = parse_json_response(cleaned)
        return result

    # 长文本使用并行分块处理
    print(f"[parse_resume_text_parallel] 文本长度: {len(text)}, 阈值: {chunk_threshold}, 需要分块", file=sys.stderr, flush=True)
    processor = ParallelChunkProcessor(provider=provider, max_concurrent=max_concurrent)
    try:
        # 分块
        print(f"[parse_resume_text_parallel] 开始分块，max_chunk_size: {max_chunk_size}", file=sys.stderr, flush=True)
        chunks = split_resume_text(text, max_chunk_size=max_chunk_size)
        print(f"[parse_resume_text_parallel] 分块完成，共 {len(chunks)} 块", file=sys.stderr, flush=True)

        # 并行处理
        chunk_results = await processor.process_chunks_parallel(
            provider, chunks, schema_desc
        )

        # 合并结果
        print(f"[parse_resume_text_parallel] 开始合并 {len(chunk_results)} 个分块结果", file=sys.stderr, flush=True)
        
        # 检查是否有成功的结果
        if not chunk_results:
            error_msg = "所有分块处理都失败，请检查 API Key 配置或网络连接"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        final_result = merge_resume_chunks(chunk_results)
        print(f"[parse_resume_text_parallel] 合并完成", file=sys.stderr, flush=True)
        logger.info("分块合并完成")

        return final_result
    finally:
        processor.close()


# 示例：如何在FastAPI中使用
"""
from fastapi import FastAPI
from parallel_chunk_processor import parse_resume_text_parallel

app = FastAPI()

@app.post("/parse-resume-parallel")
async def parse_resume_endpoint(body: ResumeParseRequest):
    \"\"\"并行解析简历文本\"\"\"
    try:
        result = await parse_resume_text_parallel(
            text=body.text,
            provider=body.provider or "doubao",
            max_concurrent=3  # 可配置
        )
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
"""