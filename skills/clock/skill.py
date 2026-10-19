"""Clock skill — tier-1 current time. Read-only."""


def handle(tool_name, args, ctx):
    if tool_name != "now":
        raise ValueError(f"unknown tool {tool_name!r}")
    return {"iso": ctx.now()}
