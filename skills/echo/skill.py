"""Echo skill — tier-1 pipeline test tool. No world access."""


def handle(tool_name, args, ctx):
    if tool_name != "echo":
        raise ValueError(f"unknown tool {tool_name!r}")
    ctx.log("echo called")
    return {"text": args["text"]}
