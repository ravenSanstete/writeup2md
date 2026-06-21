"""Typer-based command-line interface for writeup2md."""

from __future__ import annotations

import json
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import Profile, build_config, enforce_macbook_limits
from .doctor import run_doctor

app = typer.Typer(
    name="writeup2md",
    help="Convert technical writeups and tutorials from PDF or URL into image-free Markdown.",
    no_args_is_help=True,
    add_completion=False,
)


# Known subcommands. We use this list to detect `writeup2md SOURCE`
# shorthand (where SOURCE is the first arg and not a subcommand).
_KNOWN_SUBCOMMANDS = {
    "convert", "batch", "inspect", "ui", "doctor", "status", "version", "evaluate-ocr",
}

console = Console()
err_console = Console(stderr=True)


# Exit codes per docs/04_CLI_SPEC.md
EXIT_ACCEPTED = 0
EXIT_REVIEW = 2
EXIT_REJECTED = 3
EXIT_INPUT_ERROR = 4
EXIT_EXECUTION_FAILURE = 5


class ProfileOption(str, Enum):
    FAST = "fast"
    DEFAULT = "default"
    STRICT = "strict"
    MACBOOK = "macbook"


def _resolve_profile(profile: ProfileOption | None) -> Profile:
    if profile is None:
        return Profile.MACBOOK
    return Profile(profile.value)


def _not_implemented(cmd: str) -> int:
    err_console.print(
        f"[yellow]writeup2md {cmd} is not implemented in this build.[/yellow]"
    )
    return EXIT_EXECUTION_FAILURE


@app.command()
def convert(
    source: str = typer.Argument(..., help="PDF path, URL, or local HTML path."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output root directory."),
    profile: Optional[ProfileOption] = typer.Option(
        None,
        "--profile",
        "-p",
        help="Execution profile: fast, default, strict, macbook.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Strict mode (TASK_19). Routes uncertain transcriptions to "
            "review_required and allows HTML-comment markers in "
            "document.md for the review UI. Default is document mode "
            "which surfaces uncertain content with a textual notice."
        ),
    ),
    device: Optional[str] = typer.Option(None, "--device", help="auto|cpu|gpu"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing output."),
    resume: bool = typer.Option(
        True,
        "--resume/--no-resume",
        help="Resume a compatible page-checkpointed PDF workspace.",
    ),
    restart_failed: bool = typer.Option(
        False,
        "--restart-failed",
        help="Retry failed PDF page shards during resume.",
    ),
    keep_evidence: bool = typer.Option(
        True,
        "--keep-evidence/--no-keep-evidence",
        help="Preserve raw evidence assets.",
    ),
    open_ui: bool = typer.Option(False, "--open-ui", help="Open the Streamlit UI after conversion."),
    workers: int = typer.Option(1, "--workers", help="Batch workers (capped by profile)."),
    ocr_backend: Optional[str] = typer.Option(
        None,
        "--ocr-backend",
        help=(
            "OCR backend: auto (default), paddleocr-vl, paddleocr-vl-element, "
            "rapid, mlx, mock (tests only)."
        ),
    ),
    require_exact_backend: bool = typer.Option(
        False,
        "--require-exact-backend",
        help=(
            "Forbid silent fallback. If the requested backend cannot be "
            "loaded, exit nonzero instead of substituting RapidOCR."
        ),
    ),
    general_vlm: Optional[str] = typer.Option(
        None,
        "--general-vlm",
        help="Optional general VLM backend: disabled (default), auto, openai-compatible, mock.",
    ),
) -> None:
    """Convert a single PDF, URL, or local HTML file into Markdown."""
    # Lazy import so doctor/help work without optional deps.
    from .pipeline import convert_source

    prof = _resolve_profile(profile)
    cfg = build_config(prof)
    if workers != 1:
        cfg.pipeline.workers = workers
    if ocr_backend:
        cfg.ocr.backend = ocr_backend
    else:
        import platform

        if platform.system() == "Darwin" and platform.machine() == "arm64":
            cfg.ocr.backend = "paddleocr-vl-element"
            require_exact_backend = True
    if strict:
        # TASK_19: --strict overrides quality.mode without changing
        # other profile settings (workers, DPI, etc).
        cfg.quality.mode = "strict"
    if general_vlm:
        cfg.general_vlm.backend = general_vlm
    try:
        enforce_macbook_limits(cfg)
    except ValueError as e:
        err_console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(code=EXIT_INPUT_ERROR)

    out_root = output or Path("outputs")
    if require_exact_backend:
        # Probe the backend eagerly so we exit with a clear message
        # before doing any work.
        from .ocr.backend import get_backend, reset_backend, BackendIdentityError

        reset_backend()
        try:
            get_backend(cfg.ocr.backend, require_exact_backend=True)
        except BackendIdentityError as e:
            err_console.print(f"[red]Backend identity error:[/red] {e}")
            raise typer.Exit(code=EXIT_EXECUTION_FAILURE)
    try:
        result = convert_source(
            source=source,
            output_root=out_root,
            config=cfg,
            force=force,
            keep_evidence=keep_evidence,
            device=device,
            resume=resume,
            restart_failed=restart_failed,
        )
    except FileNotFoundError as e:
        err_console.print(f"[red]Input error:[/red] {e}")
        raise typer.Exit(code=EXIT_INPUT_ERROR)
    except Exception as e:  # noqa: BLE001
        if e.__class__.__name__ == "PdfCheckpointInterrupted":
            err_console.print(f"[yellow]{e}[/yellow]")
            raise typer.Exit(code=130)
        err_console.print(f"[red]Execution failure:[/red] {e}")
        raise typer.Exit(code=EXIT_EXECUTION_FAILURE)

    status = result.status
    md_path = result.document_dir / "document.md"
    console.print(f"Status: {status.upper()}")
    console.print(f"Markdown: {md_path}")
    console.print(f"Review UI: writeup2md ui {result.document_dir}")
    if open_ui:
        # Defer UI launch.
        from .ui_runner import launch_ui

        launch_ui(result.document_dir)

    if status == "accepted":
        raise typer.Exit(code=EXIT_ACCEPTED)
    if status == "review":
        raise typer.Exit(code=EXIT_REVIEW)
    if status == "rejected":
        raise typer.Exit(code=EXIT_REJECTED)
    raise typer.Exit(code=EXIT_EXECUTION_FAILURE)


@app.command()
def batch(
    input_path: Path = typer.Argument(..., help="Directory, URL list, or JSONL manifest."),
    workers: int = typer.Option(1, "--workers", help="Workers (default 1, max 2 in macbook)."),
    resume: bool = typer.Option(True, "--resume/--no-resume", help="Resume from durable state."),
    retry: int = typer.Option(0, "--retry", help="Retry attempts per source."),
    profile: Optional[ProfileOption] = typer.Option(None, "--profile", "-p"),
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Strict mode (TASK_19). Routes uncertain transcriptions to "
            "review_required and allows HTML-comment markers in "
            "document.md for the review UI."
        ),
    ),
    recursive: bool = typer.Option(False, "--recursive", help="Recurse into directories."),
    include: Optional[str] = typer.Option(None, "--include", help="Include glob."),
    exclude: Optional[str] = typer.Option(None, "--exclude", help="Exclude glob."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output root."),
    ocr_backend: Optional[str] = typer.Option(
        None,
        "--ocr-backend",
        help=(
            "OCR backend: auto, paddleocr-vl, paddleocr-vl-element, rapid, "
            "mlx, mock (tests only)."
        ),
    ),
    require_exact_backend: bool = typer.Option(
        False,
        "--require-exact-backend",
        help="Forbid silent fallback. Exit nonzero if the requested backend is unavailable.",
    ),
    force_refresh: bool = typer.Option(
        False, "--force-refresh", help="Bypass cache freshness checks; always re-process."
    ),
    max_age: Optional[int] = typer.Option(
        None, "--max-age", help="Treat cached results as fresh if younger than SECONDS."
    ),
) -> None:
    """Process multiple sources with resume support."""
    from .batch import run_batch

    prof = _resolve_profile(profile)
    cfg = build_config(prof)
    cfg.pipeline.workers = workers
    cfg.pipeline.resume = resume
    if ocr_backend:
        cfg.ocr.backend = ocr_backend
    if strict:
        cfg.quality.mode = "strict"
    try:
        enforce_macbook_limits(cfg)
    except ValueError as e:
        err_console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(code=EXIT_INPUT_ERROR)

    out_root = output or Path("outputs")
    if require_exact_backend:
        from .ocr.backend import get_backend, reset_backend, BackendIdentityError

        reset_backend()
        try:
            get_backend(cfg.ocr.backend, require_exact_backend=True)
        except BackendIdentityError as e:
            err_console.print(f"[red]Backend identity error:[/red] {e}")
            raise typer.Exit(code=EXIT_EXECUTION_FAILURE)
    summary = run_batch(
        input_path=input_path,
        output_root=out_root,
        config=cfg,
        recursive=recursive,
        include=include,
        exclude=exclude,
        retry=retry,
        force_refresh=force_refresh,
        max_age=max_age,
    )
    console.print(f"Batch complete: {summary.total} sources")
    console.print(
        f"  accepted={summary.accepted} review={summary.review} "
        f"rejected={summary.rejected} failed={summary.failed}"
    )
    if summary.failed:
        raise typer.Exit(code=EXIT_EXECUTION_FAILURE)
    if summary.rejected:
        raise typer.Exit(code=EXIT_REJECTED)
    if summary.review:
        raise typer.Exit(code=EXIT_REVIEW)
    raise typer.Exit(code=EXIT_ACCEPTED)


@app.command()
def inspect(
    result_dir: Path = typer.Argument(..., help="Document output directory to inspect."),
    export_reviews_path: Optional[Path] = typer.Option(
        None,
        "--export-reviews",
        help="Export human revisions (review_state + revisions.jsonl) as JSONL to PATH.",
    ),
) -> None:
    """Print source, status, quality metrics and artifact paths for a document."""
    from .inspect_cmd import export_reviews, inspect_document

    try:
        info = inspect_document(result_dir)
    except FileNotFoundError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=EXIT_INPUT_ERROR)

    table = Table(title=f"Document: {info.document_id}")
    table.add_column("field")
    table.add_column("value")
    table.add_row("source", info.source)
    table.add_row("source_type", info.source_type)
    table.add_row("status", info.status)
    table.add_row("quality_score", f"{info.quality_score:.3f}")
    table.add_row("blocks", str(info.block_count))
    table.add_row("unresolved_visuals", str(info.unresolved_visuals))
    table.add_row("markdown_images", str(info.markdown_images))
    console.print(table)

    paths = Table(title="Artifacts")
    paths.add_column("name")
    paths.add_column("path")
    for name, p in info.artifacts.items():
        paths.add_row(name, str(p))
    console.print(paths)

    if export_reviews_path is not None:
        try:
            n = export_reviews(result_dir, export_reviews_path)
        except FileNotFoundError as e:
            err_console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=EXIT_INPUT_ERROR)
        console.print(
            f"[green]Exported {n} review record(s) to {export_reviews_path}[/green]"
        )


@app.command()
def ui(
    result_root: Optional[Path] = typer.Argument(
        None, help="Result root or single document directory."
    ),
    port: int = typer.Option(8501, "--port", help="Streamlit port."),
) -> None:
    """Launch the Streamlit review UI."""
    from .ui_runner import launch_ui

    root = result_root or Path("outputs")
    launch_ui(root, port=port)


@app.command()
def status(
    result_dir: Path = typer.Argument(..., help="Page-checkpointed PDF output directory."),
) -> None:
    """Show page-level PDF checkpoint progress."""
    from .pdf_checkpoint import read_pdf_checkpoint_status

    try:
        progress = read_pdf_checkpoint_status(result_dir)
    except Exception as e:  # noqa: BLE001
        err_console.print(f"[red]Unable to read checkpoint status:[/red] {e}")
        raise typer.Exit(code=EXIT_INPUT_ERROR)
    console.print(f"Pages total: {progress.pages_total}")
    console.print(f"Verified: {progress.verified}")
    console.print(f"Processing: {progress.processing}")
    console.print(f"Pending: {progress.pending}")
    console.print(f"Failed: {progress.failed}")
    last = progress.last_completed_page if progress.last_completed_page is not None else "-"
    console.print(f"Last completed page: {last}")


@app.command()
def doctor(
    output_root: Optional[Path] = typer.Option(
        None, "--output-root", help="Output root to probe for writability."
    ),
    require_ocr: bool = typer.Option(
        False,
        "--require-ocr",
        help="Exit nonzero if no real OCR backend can run (mock does not count).",
    ),
    require_paddleocr_vl: bool = typer.Option(
        False,
        "--require-paddleocr-vl",
        help=(
            "Exit nonzero unless a PaddleOCR-VL backend (full or element) "
            "is available. Stronger than --require-ocr, which is satisfied "
            "by RapidOCR alone."
        ),
    ),
    smoke_ocr: Optional[Path] = typer.Option(
        None,
        "--smoke-ocr",
        help="Run one real OCR inference on the given image path and print metadata.",
    ),
    ocr_backend: Optional[str] = typer.Option(
        None,
        "--ocr-backend",
        help=(
            "When used with --smoke-ocr, force a specific backend "
            "(paddleocr-vl, paddleocr-vl-element, rapid, mlx, auto). "
            "Default: auto."
        ),
    ),
    require_exact_backend: bool = typer.Option(
        False,
        "--require-exact-backend",
        help=(
            "With --smoke-ocr --ocr-backend NAME, forbid silent fallback "
            "to a different backend. Exit nonzero if NAME is unavailable."
        ),
    ),
) -> None:
    """Check Python, dependencies, OCR backends, Playwright, and output permissions."""
    from .doctor import run_doctor, smoke_ocr as doctor_smoke_ocr

    report = run_doctor(output_root=output_root)
    table = Table(title=f"writeup2md doctor — v{__version__}")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail")
    for c in report.checks:
        status = "[green]OK[/green]" if c.ok else (
            "[red]FAIL[/red]" if c.required else "[yellow]missing[/yellow]"
        )
        table.add_row(c.name, status, c.detail)
    console.print(table)

    if require_ocr:
        from .ocr.backend import available_backends

        avail = available_backends()
        if not avail:
            err_console.print(
                "[red]--require-ocr failed:[/red] no real OCR backend available. "
                "Install one of: paddleocr+paddlepaddle, transformers+torch, "
                "rapidocr-onnxruntime, mlx-vlm."
            )
            raise typer.Exit(code=EXIT_EXECUTION_FAILURE)
        console.print(f"[green]--require-ocr OK:[/green] real backends: {','.join(avail)}")

    if require_paddleocr_vl:
        from .ocr.backend import available_backends, BackendIdentityError, get_backend, reset_backend

        avail = available_backends()
        paddleocr_vl_avail = [b for b in avail if b.startswith("paddleocr-vl")]
        if not paddleocr_vl_avail:
            err_console.print(
                "[red]--require-paddleocr-vl failed:[/red] "
                "no PaddleOCR-VL backend available. Install one of: "
                "paddleocr + paddlepaddle (full pipeline), "
                "transformers + torch (element mode). "
                f"Available backends: {avail or 'none'}."
            )
            raise typer.Exit(code=EXIT_EXECUTION_FAILURE)
        # Verify exact identity by attempting a strict probe.
        reset_backend()
        try:
            backend = get_backend(
                paddleocr_vl_avail[0],
                require_exact_backend=True,
            )
        except BackendIdentityError as e:
            err_console.print(
                f"[red]--require-paddleocr-vl failed:[/red] {e}"
            )
            raise typer.Exit(code=EXIT_EXECUTION_FAILURE)
        meta_repo = ""
        meta_revision = ""
        try:
            # We do not run an inference here — just confirm the backend
            # would load with the right identity. The identity fields
            # will be populated on first recognize(); for the doctor
            # check we rely on the probe + identity verification that
            # already happened inside _load_model_strict.
            from .ocr.model_identity import (
                PADDLEOCR_VL_REPO,
                PADDLEOCR_VL_REVISION,
                cached_identity,
            )
            identity = cached_identity()
            meta_repo = identity.repo if identity else PADDLEOCR_VL_REPO
            meta_revision = identity.revision if identity else PADDLEOCR_VL_REVISION
        except Exception:  # noqa: BLE001
            pass
        console.print(
            f"[green]--require-paddleocr-vl OK:[/green] "
            f"backend={getattr(backend, 'name', '?')} "
            f"repo={meta_repo} sha={meta_revision[:12]}"
        )

    if smoke_ocr is not None:
        console.print(f"\n[bold]OCR smoke test on {smoke_ocr}:[/bold]")
        try:
            out = doctor_smoke_ocr(
                smoke_ocr,
                output_path=Path("reports/doctor_smoke_ocr.json"),
                backend_name=ocr_backend or "auto",
                require_exact_backend=require_exact_backend,
            )
        except Exception as e:  # noqa: BLE001
            err_console.print(f"[red]OCR smoke test FAILED:[/red] {e}")
            raise typer.Exit(code=EXIT_EXECUTION_FAILURE)
        console.print(
            f"  backend={out['backend']} version={out['backend_version']} "
            f"is_mock={out['is_mock']}"
        )
        console.print(
            f"  model={out.get('model_name')} device={out.get('device')} "
            f"dims={out.get('input_dimensions')}"
        )
        console.print(
            f"  load={out.get('load_duration_s', 0):.3f}s "
            f"infer={out.get('inference_duration_s', 0):.3f}s "
            f"regions={out.get('region_count')}"
        )
        console.print(f"  raw_output_path={out.get('raw_output_path')}")
        if out.get("is_mock"):
            err_console.print("[red]smoke test used mock backend — failing.[/red]")
            raise typer.Exit(code=EXIT_EXECUTION_FAILURE)
        console.print("  [green]OCR smoke test OK[/green]")

    if not report.all_required_ok:
        raise typer.Exit(code=EXIT_EXECUTION_FAILURE)


@app.command()
def version() -> None:
    """Print the writeup2md version."""
    console.print(f"writeup2md {__version__}")


@app.command(name="evaluate-ocr")
def evaluate_ocr(
    golden_dir: Path = typer.Argument(..., help="Golden Set directory (contains manifest.jsonl)."),
    backend: str = typer.Option(
        "auto",
        "--backend",
        help="OCR backend: auto, paddleocr-vl, paddleocr-vl-element, rapid, mlx.",
    ),
    output: Path = typer.Option(Path("reports/golden-eval"), "--output", "-o", help="Output dir for eval reports."),
) -> None:
    """Evaluate a real OCR backend against the Golden Set."""
    from .evaluate import evaluate_golden_set

    try:
        result = evaluate_golden_set(
            golden_dir=golden_dir,
            backend_name=backend,
            output_dir=output,
        )
    except Exception as e:  # noqa: BLE001
        err_console.print(f"[red]evaluate-ocr failed:[/red] {e}")
        raise typer.Exit(code=EXIT_EXECUTION_FAILURE)

    s = result["summary"]
    console.print(f"Backend: {result['backend']} v{result['backend_version']}")
    console.print(f"Samples: {s['sample_count']}")
    console.print(f"CER mean: {s['cer_mean']:.4f}")
    console.print(f"Char accuracy mean: {s['char_accuracy_mean']:.4f}")
    console.print(f"Exact match rate: {s['exact_match_rate']:.4f}")
    console.print(f"Critical-token recall mean: {s['critical_token_recall_mean']:.4f}")
    cal = result["calibration"]
    console.print(
        f"Calibration: accepted_precision={cal['accepted_precision']:.4f} "
        f"(accepted={cal['accepted_count']}, review={cal['review_count']})"
    )
    console.print(f"Reports written to: {output}")
    console.print("  - results.jsonl (per-sample)")
    console.print("  - summary.json")
    console.print("  - by_visual_type.json")
    console.print("  - reports/GOLDEN_SET_METRICS.json")
    console.print("  - reports/GOLDEN_SET_METRICS.md")


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
) -> None:
    """writeup2md — image-free Markdown from PDFs and URLs of technical writeups.

    TASK_20: `writeup2md SOURCE` is a shorthand for `writeup2md convert SOURCE`.
    If the first argument is not a known subcommand, treat it as a SOURCE and
    route to convert.
    """
    if ctx.invoked_subcommand is None and ctx.args:
        # The user typed `writeup2md SOURCE [convert-options]`. Route to
        # convert by re-invoking the convert command with the same args.
        from typer import Option as _Opt

        # Build the convert command's argument list. ctx.args contains
        # the trailing args after the program name (no subcommand).
        # We just call the convert function directly with parsed args.
        argv = list(ctx.args)
        # Parse out the SOURCE (first positional).
        if not argv:
            typer.echo("Error: SOURCE argument required.", err=True)
            raise typer.Exit(code=EXIT_INPUT_ERROR)
        source = argv[0]
        rest = argv[1:]
        # Parse known options. We accept the same options as `convert`.
        # Simple parse: walk rest, look for --opt value pairs.
        opts = {
            "output": None,
            "profile": None,
            "strict": False,
            "device": None,
            "force": False,
            "keep_evidence": True,
            "open_ui": False,
            "workers": 1,
            "ocr_backend": None,
            "require_exact_backend": False,
        }
        i = 0
        while i < len(rest):
            arg = rest[i]
            if arg in ("-o", "--output") and i + 1 < len(rest):
                opts["output"] = Path(rest[i + 1])
                i += 2
            elif arg in ("-p", "--profile") and i + 1 < len(rest):
                opts["profile"] = ProfileOption(rest[i + 1])
                i += 2
            elif arg == "--strict":
                opts["strict"] = True
                i += 1
            elif arg == "--device" and i + 1 < len(rest):
                opts["device"] = rest[i + 1]
                i += 2
            elif arg == "--force":
                opts["force"] = True
                i += 1
            elif arg == "--no-keep-evidence":
                opts["keep_evidence"] = False
                i += 1
            elif arg == "--keep-evidence":
                opts["keep_evidence"] = True
                i += 1
            elif arg == "--open-ui":
                opts["open_ui"] = True
                i += 1
            elif arg == "--workers" and i + 1 < len(rest):
                opts["workers"] = int(rest[i + 1])
                i += 2
            elif arg == "--ocr-backend" and i + 1 < len(rest):
                opts["ocr_backend"] = rest[i + 1]
                i += 2
            elif arg == "--require-exact-backend":
                opts["require_exact_backend"] = True
                i += 1
            else:
                typer.echo(f"Error: unknown option {arg!r}", err=True)
                raise typer.Exit(code=EXIT_INPUT_ERROR)
        # TASK_20.B: on Apple Silicon, default to paddleocr-vl-element
        # with require_exact_backend=true. The user can still override
        # with --ocr-backend or --no-require-exact-backend (future).
        import platform

        is_apple_silicon = (
            platform.system() == "Darwin" and platform.machine() == "arm64"
        )
        if is_apple_silicon and opts["ocr_backend"] is None:
            opts["ocr_backend"] = "paddleocr-vl-element"
        if is_apple_silicon and not opts["require_exact_backend"]:
            # Only auto-enable require_exact_backend when the user did not
            # explicitly request a different backend.
            if opts["ocr_backend"] == "paddleocr-vl-element":
                opts["require_exact_backend"] = True
        # Invoke the convert function directly.
        ctx.invoke(
            convert,
            source=source,
            output=opts["output"],
            profile=opts["profile"],
            strict=opts["strict"],
            device=opts["device"],
            force=opts["force"],
            keep_evidence=opts["keep_evidence"],
            open_ui=opts["open_ui"],
            workers=opts["workers"],
            ocr_backend=opts["ocr_backend"],
            require_exact_backend=opts["require_exact_backend"],
        )
        return
    if ctx.invoked_subcommand is None:
        # No args at all — show help.
        typer.echo(ctx.get_help())


if __name__ == "__main__":
    main()


def main() -> None:
    """Entry point for the `writeup2md` script.

    TASK_20.A: `writeup2md SOURCE` shorthand. If the first argv is
    not a known subcommand, prepend `convert` so the rest of the
    args are parsed as convert options.
    """
    argv = sys.argv[1:]
    if argv and argv[0] not in _KNOWN_SUBCOMMANDS and not argv[0].startswith("-"):
        sys.argv = [sys.argv[0], "convert"] + argv
    app()
