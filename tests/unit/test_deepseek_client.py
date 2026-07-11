from harness.llm.deepseek import DeepSeekClient, _redact


def test_constructs():
    c = DeepSeekClient(api_key="sk-abcdefgh1234567890", model="deepseek-chat",
                       base_url="https://api.deepseek.com")
    assert c.model == "deepseek-chat"
    assert callable(c.chat)


def test_redact():
    assert _redact(None) == "<unset>"
    assert _redact("sk-1234567890abcdef") == "sk-***...***def"
    assert _redact("short") == "***"