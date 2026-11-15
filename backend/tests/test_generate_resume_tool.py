from backend.core.logger import setup_logging
setup_logging(False, 'INFO', 'logs/test')

from backend.agent.tool.generate_resume_tool import GenerateResumeTool


def test_generate_resume_tool_schema():
    tool = GenerateResumeTool()
    assert tool.name == "generate_resume"
    props = tool.parameters["properties"]
    assert "job_description" in props
    assert "user_background" in props
