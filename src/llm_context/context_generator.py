import random
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader  # type: ignore

from llm_context.exec_env import ProjectConfig
from llm_context.file_selector import FileSelector
from llm_context.folder_structure_diagram import get_annotated_fsd
from llm_context.highlighter.language_mapping import to_language
from llm_context.highlighter.outliner import generate_outlines
from llm_context.highlighter.parser import Source
from llm_context.state import FileSelection
from llm_context.utils import PathConverter, safe_read_file


@dataclass(frozen=True)
class Template:
    name: str
    context: dict
    env: Environment

    @staticmethod
    def create(name: str, context: dict, templates_path) -> "Template":
        env = Environment(loader=FileSystemLoader(str(templates_path)))
        return Template(name, context, env)

    def render(self) -> str:
        template = self.env.get_template(self.name)
        return template.render(**self.context)


@dataclass(frozen=True)
class ContextCollector:
    root_path: Path

    @staticmethod
    def create(root_path: Path) -> "ContextCollector":
        return ContextCollector(root_path)

    def sample_file_abs(self, full_abs: list[str]) -> list[str]:
        all_abs = set(FileSelector.create(self.root_path, [".git"]).get_files())
        incomplete_files = sorted(list(all_abs - set(full_abs)))
        return random.sample(incomplete_files, min(2, len(incomplete_files)))

    def files(self, rel_paths: list[str]) -> list[dict[str, str]]:
        abs_paths = PathConverter.create(self.root_path).to_absolute(rel_paths)
        return [
            {"path": rel_path, "content": content}
            for rel_path, abs_path in zip(rel_paths, abs_paths)
            if (content := safe_read_file(abs_path)) is not None
        ]

    def outlines(self, rel_paths: list[str]) -> list[dict[str, str]]:
        abs_paths = PathConverter.create(self.root_path).to_absolute(rel_paths)
        source_set = [
            Source(rel, content)
            for rel, abs_path in zip(rel_paths, abs_paths)
            if (content := safe_read_file(abs_path)) is not None
        ]
        return generate_outlines(source_set)

    def folder_structure_diagram(
        self, full_abs: list[str], outline_abs: list[str], no_media: bool
    ) -> str:
        return get_annotated_fsd(self.root_path, full_abs, outline_abs, no_media)


@dataclass(frozen=True)
class ContextGenerator:
    collector: ContextCollector
    settings: ProjectConfig
    project_root: Path
    converter: PathConverter
    full_rel: list[str]
    full_abs: list[str]
    outline_rel: list[str]
    outline_abs: list[str]

    @staticmethod
    def create(settings: ProjectConfig, file_selection: FileSelection) -> "ContextGenerator":
        project_root = settings.project_root_path
        collector = ContextCollector.create(project_root)
        converter = PathConverter.create(project_root)
        sel_files = file_selection
        full_rel = sel_files.full_files
        full_abs = converter.to_absolute(full_rel)
        outline_rel = [f for f in sel_files.outline_files if to_language(f)]
        outline_abs = converter.to_absolute(outline_rel)

        return ContextGenerator(
            collector,
            settings,
            project_root,
            converter,
            full_rel,
            full_abs,
            outline_rel,
            outline_abs,
        )

    def files(self, in_files: list[str] = []) -> str:
        rel_paths = in_files if in_files else self.full_rel
        return self._render("files", {"files": self.collector.files(rel_paths)})

    def context(self) -> str:
        descriptor = self.settings.context_descriptor
        layout = self.settings.project_layout
        ctx_settings = descriptor.get_settings()
        (no_media, with_prompt) = (ctx_settings["no_media"], ctx_settings["with_prompt"])
        context = {
            "project_name": self.project_root.name,
            "folder_structure_diagram": self.collector.folder_structure_diagram(
                self.full_abs, self.outline_abs, no_media
            ),
            "files": self.collector.files(self.full_rel),
            "highlights": self.collector.outlines(self.outline_rel),
            "sample_requested_files": self.converter.to_relative(
                self.collector.sample_file_abs(self.full_abs)
            ),
            "prompt": descriptor.get_prompt(layout) if with_prompt else None,
        }
        return self._render("context", context)

    def _render(self, template_id: str, context: dict) -> str:
        template_name = self.settings.templates[template_id]
        template = Template.create(
            template_name, context, self.settings.project_layout.templates_path
        )
        return template.render()
