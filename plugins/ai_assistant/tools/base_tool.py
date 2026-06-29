try:
    from ..ai_core.tool_spec import ToolSpec
except ImportError:
    try:
        from plugins.ai_assistant.ai_core.tool_spec import ToolSpec
    except ImportError:
        import importlib

        ToolSpec = importlib.import_module("ai_core.tool_spec").ToolSpec


class BaseTool:
    def __init__(self, name, description, args_schema, metadata=None):
        self.name = name
        self.description = description
        self.args_schema = args_schema
        self.metadata = metadata or {}

    @property
    def side_effect_level(self):
        return self.metadata.get("side_effect_level", "none")

    @property
    def source(self):
        return self.metadata.get("source", "local")

    @property
    def display_name(self):
        return self.metadata.get("display_name")

    @property
    def risk_level(self):
        return self.metadata.get("risk_level", "low")

    @property
    def output_type(self):
        return self.metadata.get("output_type", "text")

    @property
    def requires_verification(self):
        return bool(self.metadata.get("requires_verification", False))

    @property
    def requires_read_before_write(self):
        return bool(self.metadata.get("requires_read_before_write", False))

    @property
    def is_verification_tool(self):
        return bool(self.metadata.get("is_verification_tool", False))

    @property
    def lifecycle_role(self):
        return self.metadata.get("lifecycle_role", "normal")

    @property
    def required_args(self):
        names = self.metadata.get("required_args")
        if isinstance(names, (list, tuple)):
            return [str(name) for name in names if str(name).strip()]
        return []

    @property
    def path_argument_names(self):
        names = self.metadata.get("path_argument_names")
        if isinstance(names, (list, tuple)) and names:
            return list(names)
        return ["filepath", "file_path"]

    @property
    def capability_tags(self):
        tags = self.metadata.get("capability_tags")
        if isinstance(tags, (list, tuple)):
            return [str(tag) for tag in tags if str(tag).strip()]
        return []

    @property
    def domain_tags(self):
        tags = self.metadata.get("domain_tags")
        if isinstance(tags, (list, tuple)):
            return [str(tag) for tag in tags if str(tag).strip()]
        return []

    @property
    def usage_hint(self):
        return str(self.metadata.get("usage_hint", "") or "")

    @property
    def keywords(self):
        values = self.metadata.get("keywords")
        if isinstance(values, (list, tuple)):
            return [str(value) for value in values if str(value).strip()]
        return []

    @property
    def server_name(self):
        value = self.metadata.get("server_name")
        return str(value) if value else None

    @property
    def spec(self):
        return ToolSpec(
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
            display_name=self.display_name,
            source=self.source,
            side_effect_level=self.side_effect_level,
            risk_level=self.risk_level,
            output_type=self.output_type,
            requires_verification=self.requires_verification,
            requires_read_before_write=self.requires_read_before_write,
            is_verification_tool=self.is_verification_tool,
            lifecycle_role=self.lifecycle_role,
            required_args=self.required_args,
            path_argument_names=self.path_argument_names,
            capability_tags=self.capability_tags,
            domain_tags=self.domain_tags,
            keywords=self.keywords,
            usage_hint=self.usage_hint,
            server_name=self.server_name,
            metadata=dict(self.metadata),
        )

    def execute(self, **kwargs):
        """执行工具功能。可以是一个普通的函数，也可以是一个 async 函数。"""
        raise NotImplementedError
