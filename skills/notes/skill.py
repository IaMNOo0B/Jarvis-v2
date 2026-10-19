"""Notes skill — tier-2 file notes, jailed to the skill's data directory.

All paths are relative to the jail. Absolute paths and ``..`` escapes are
denied by SkillContext before any file is touched.
"""


def handle(tool_name, args, ctx):
    if tool_name == "notes_write":
        ctx.write_file(args["path"], args["content"])
        ctx.log(f"wrote note {args['path']!r}")
        return {"path": args["path"], "written": True}
    if tool_name == "notes_read":
        content = ctx.read_file(args["path"])
        return {"path": args["path"], "content": content}
    if tool_name == "notes_list":
        return {"notes": ctx.list_dir("")}
    raise ValueError(f"unknown tool {tool_name!r}")
