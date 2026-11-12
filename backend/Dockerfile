# ============================================================
# Resume-Agent 后端镜像：FastAPI + XeLaTeX 中文简历编译环境
#
# 构建上下文必须是仓库根目录（依赖根目录 requirements.txt、
# latex-resume-template/ 模板与 config.toml）：
#   docker build -f backend/Dockerfile -t resume-agent-backend .
# ============================================================
FROM python:3.12-slim

# 系统依赖说明：
# - texlive-xetex / texlive-lang-chinese / texlive-latex-* / texlive-fonts-*：
#   XeLaTeX 中文简历 PDF 编译全量环境
# 系统依赖说明：
# - texlive-xetex / texlive-lang-chinese / texlive-latex-* / texlive-fonts-*：
#   XeLaTeX 中文简历 PDF 编译全量环境
# - fontconfig：中文字体注册与 fc-cache 缓存刷新
# - curl：容器 HEALTHCHECK 探针
# - gcc / g++ / libpq-dev：部分 Python 依赖源码编译 + PostgreSQL 驱动
RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-xetex \
        texlive-lang-chinese \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        fontconfig \
        curl \
        gcc \
        g++ \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=9000

# 先装依赖再拷代码，充分利用 Docker 层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 补充安装 texlive-plain-generic（提供 ulem.sty 等通用排版宏包）
RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-plain-generic \
    && rm -rf /var/lib/apt/lists/*

# 后端代码、XeLaTeX 模板（含 fonts/zh_CN-Adobe 中文字体）与模型配置
# （backend/services/zhipu_layout.py 按仓库根相对路径读取 config.toml）
COPY backend/ ./backend/
COPY latex-resume-template/ ./latex-resume-template/
COPY config.toml ./config.toml

# 数据与日志持久化目录（docker-compose 挂载卷的目标位置）
RUN mkdir -p /app/data /app/logs

# 刷新字体缓存，注册模板内置中文字体与 TeX Live 西文字体
RUN fc-cache -fv

EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD curl -f http://localhost:9000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "9000"]
