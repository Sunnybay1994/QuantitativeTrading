"""Focused contract tests for two-component M3 artifact publication."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from quant.research.m3._artifact_publication import (
    ArtifactPublication,
    ArtifactPublicationError,
    ArtifactRollbackError,
)


def _empty_root(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir()
    return root


def test_nested_and_flat_files_commit_as_one_exact_tree(tmp_path: Path) -> None:
    root = _empty_root(tmp_path, "exact-tree")
    expected = {"manifest.json", "receipt.json"}
    expected.update(
        f"scenario-{scenario}/table-{table}.parquet"
        for scenario in range(3)
        for table in range(9)
    )
    assert len(expected) == 29

    with ArtifactPublication(root) as publication:
        for index, name in enumerate(reversed(sorted(expected))):
            raw = f"payload-{index}".encode()
            publication.write_bytes(name, raw)
            assert publication.read_bytes(name) == raw
            assert publication.sha256(name) == hashlib.sha256(raw).hexdigest()
        publication.commit(tuple(reversed(sorted(expected))))

    actual = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file()
    }
    assert actual == expected
    assert {item.name for item in root.iterdir() if item.is_dir()} == {
        "scenario-0", "scenario-1", "scenario-2",
    }


@pytest.mark.parametrize(
    "name",
    [
        "", ".", "..", "/absolute", "C:/drive", "//server/share",
        "a//b", "a/./b", "a/../b", "a\\b", "a:b", "a\x00b",
        "a/b/c", "CON", "con.txt", "a/COM1.bin", "a/NUL", " trailing",
        "trailing ", "trailing.", ".hidden", "a/.hidden", "a/",
        "a" * 129, f"{'a' * 128}/{'b' * 129}",
    ],
)
def test_noncanonical_paths_fail_before_new_output(
    tmp_path: Path, name: str,
) -> None:
    root = _empty_root(tmp_path, f"invalid-{abs(hash(name))}")
    with pytest.raises(ArtifactPublicationError) as caught:
        with ArtifactPublication(root) as publication:
            publication.write_bytes(name, b"forbidden")
    assert caught.value.args == ()
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert not any(root.iterdir())


@pytest.mark.parametrize(
    "first,second",
    [
        ("Case.bin", "case.bin"),
        ("Dir/a.bin", "dir/b.bin"),
        ("x", "x/a.bin"),
        ("x/a.bin", "x"),
        ("x/A.bin", "x/a.bin"),
    ],
)
def test_case_and_file_directory_aliases_fail_closed(
    tmp_path: Path, first: str, second: str,
) -> None:
    root = _empty_root(tmp_path, f"alias-{first.replace('/', '-')}")
    with pytest.raises(ArtifactPublicationError):
        with ArtifactPublication(root) as publication:
            publication.write_bytes(first, b"first")
            publication.write_bytes(second, b"second")
    assert not any(root.iterdir())


def test_expected_names_use_same_parser_and_reject_duplicates(
    tmp_path: Path,
) -> None:
    invalid_expected: tuple[Any, ...] = (
        ["a.bin", "a.bin"],
        ["a.bin", "A.bin"],
        ["a.bin", "a.bin/child"],
        ["dir/a.bin", "DIR/b.bin"],
        ["dir"],
        ["dir/a/b.bin"],
    )
    for index, expected in enumerate(invalid_expected):
        root = _empty_root(tmp_path, f"invalid-expected-{index}")
        with pytest.raises(ArtifactPublicationError):
            with ArtifactPublication(root) as publication:
                publication.write_bytes("a.bin", b"owned")
                publication.commit(expected)
        assert not any(root.iterdir())


def test_preexisting_child_and_leaf_are_never_adopted_or_clobbered(
    tmp_path: Path,
) -> None:
    preexisting = _empty_root(tmp_path, "preexisting-child")
    child = preexisting / "scenario"
    child.mkdir()
    sentinel = child / "sentinel.bin"
    sentinel.write_bytes(b"foreign")
    with pytest.raises(ArtifactPublicationError):
        with ArtifactPublication(preexisting):
            raise AssertionError("non-empty root entered")
    assert sentinel.read_bytes() == b"foreign"

    root = _empty_root(tmp_path, "preexisting-leaf")
    publication = ArtifactPublication(root)
    publication.__enter__()
    publication.write_bytes("scenario/owned.bin", b"owned")
    competitor = root / "scenario" / "competitor.bin"
    competitor.write_bytes(b"competitor")
    with pytest.raises(ArtifactPublicationError):
        publication.write_bytes("scenario/competitor.bin", b"clobber")
    with pytest.raises(ArtifactRollbackError):
        publication.__exit__(None, None, None)
    assert competitor.read_bytes() == b"competitor"


def test_nested_writer_failure_is_redacted_and_rolls_back(
    tmp_path: Path,
) -> None:
    root = _empty_root(tmp_path, "writer-failure")

    def hostile(_: Any) -> None:
        try:
            raise ValueError("PRIVATE_INNER_TOKEN")
        except ValueError as error:
            raise RuntimeError("PRIVATE_OUTER_SQL") from error

    with pytest.raises(ArtifactPublicationError) as caught:
        with ArtifactPublication(root) as publication:
            publication.write_stream("scenario/data.bin", hostile)
    assert caught.value.args == ()
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "PRIVATE" not in repr(caught.value)
    assert not any(root.iterdir())


def test_post_open_identity_recheck_precedes_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _empty_root(tmp_path, "post-open")
    writer_calls = 0
    with pytest.raises(ArtifactPublicationError):
        with ArtifactPublication(root) as publication:
            real_require = publication._require_current_root
            calls = 0

            def fail_once_after_open() -> None:
                nonlocal calls
                calls += 1
                if calls == 4:
                    monkeypatch.setattr(
                        publication, "_require_current_root", real_require
                    )
                    raise RuntimeError("PRIVATE_POST_OPEN")
                real_require()

            def writer(_: Any) -> None:
                nonlocal writer_calls
                writer_calls += 1

            monkeypatch.setattr(
                publication, "_require_current_root", fail_once_after_open
            )
            publication.write_stream("scenario/data.bin", writer)
    assert writer_calls == 0
    assert not any(root.iterdir())


def test_foreign_child_entry_causes_owned_only_rollback_failure(
    tmp_path: Path,
) -> None:
    root = _empty_root(tmp_path, "foreign-child-entry")
    publication = ArtifactPublication(root)
    publication.__enter__()
    publication.write_bytes("scenario/owned.bin", b"owned")
    foreign = root / "scenario" / "foreign.bin"
    foreign.write_bytes(b"foreign")
    with pytest.raises(ArtifactPublicationError):
        publication.commit({"scenario/owned.bin"})
    with pytest.raises(ArtifactRollbackError) as caught:
        publication.__exit__(None, None, None)
    assert caught.value.args == ()
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert foreign.read_bytes() == b"foreign"
    assert not (root / "scenario" / "owned.bin").exists()


def test_added_hard_link_invalidates_owned_leaf_and_is_preserved(
    tmp_path: Path,
) -> None:
    root = _empty_root(tmp_path, "hard-link")
    publication = ArtifactPublication(root)
    publication.__enter__()
    publication.write_bytes("scenario/owned.bin", b"owned")
    owned = root / "scenario" / "owned.bin"
    alias = root / "scenario" / "alias.bin"
    os.link(owned, alias)
    with pytest.raises(ArtifactPublicationError):
        publication.read_bytes("scenario/owned.bin")
    with pytest.raises(ArtifactRollbackError):
        publication.__exit__(None, None, None)
    assert owned.read_bytes() == b"owned" and alias.read_bytes() == b"owned"


def test_child_replacement_is_blocked_or_identity_aware(
    tmp_path: Path,
) -> None:
    root = _empty_root(tmp_path, "child-replacement")
    moved = tmp_path / "child-replacement-moved"
    replacement = root / "scenario"
    publication = ArtifactPublication(root)
    publication.__enter__()
    publication.write_bytes("scenario/owned.bin", b"owned")
    if os.name == "nt":
        with pytest.raises(OSError):
            os.rename(replacement, moved)
        publication.commit({"scenario/owned.bin"})
        publication.__exit__(None, None, None)
        assert not moved.exists() and replacement.joinpath("owned.bin").exists()
        return

    os.rename(replacement, moved)
    replacement.mkdir()
    sentinel = replacement / "foreign.bin"
    sentinel.write_bytes(b"foreign")
    with pytest.raises(ArtifactPublicationError):
        publication.read_bytes("scenario/owned.bin")
    with pytest.raises(ArtifactRollbackError):
        publication.__exit__(None, None, None)
    assert sentinel.read_bytes() == b"foreign"
    assert (moved / "owned.bin").read_bytes() == b"owned"


def test_same_root_thread_race_admits_only_one_owner(tmp_path: Path) -> None:
    root = _empty_root(tmp_path, "thread-race")
    attempted = threading.Event()
    failures: list[type[BaseException]] = []

    def competitor() -> None:
        try:
            with ArtifactPublication(root):
                raise AssertionError("second owner entered")
        except BaseException as error:
            failures.append(type(error))
        finally:
            attempted.set()

    with ArtifactPublication(root) as publication:
        thread = threading.Thread(target=competitor)
        thread.start()
        assert attempted.wait(timeout=10)
        thread.join(timeout=10)
        publication.write_bytes("scenario/winner.bin", b"winner")
        publication.commit({"scenario/winner.bin"})
    assert failures == [ArtifactPublicationError]
    assert (root / "scenario" / "winner.bin").read_bytes() == b"winner"


def test_same_root_process_race_is_rejected_by_lease(tmp_path: Path) -> None:
    root = _empty_root(tmp_path, "process-race")
    script = """
import sys
from pathlib import Path
from quant.research.m3._artifact_publication import ArtifactPublication, ArtifactPublicationError
try:
    with ArtifactPublication(Path(sys.argv[1])):
        raise AssertionError('second process entered')
except ArtifactPublicationError:
    print('PROCESS_BLOCKED')
else:
    raise SystemExit(3)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd() / "src")
    with ArtifactPublication(root) as publication:
        result = subprocess.run(
            [sys.executable, "-c", script, str(root)],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0 and result.stdout.strip() == "PROCESS_BLOCKED"
        publication.write_bytes("scenario/winner.bin", b"winner")
        publication.commit({"scenario/winner.bin"})
    assert (root / "scenario" / "winner.bin").read_bytes() == b"winner"


def test_injected_child_link_is_never_adopted(tmp_path: Path) -> None:
    root = _empty_root(tmp_path, "child-link")
    target = _empty_root(tmp_path, "child-link-target")
    link = root / "scenario"
    publication = ArtifactPublication(root)
    publication.__enter__()
    if os.name == "nt":
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            publication.__exit__(None, None, None)
            pytest.skip("host does not permit junction creation")
    else:
        link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ArtifactPublicationError):
        publication.write_bytes("scenario/data.bin", b"forbidden")
    with pytest.raises(ArtifactRollbackError):
        publication.__exit__(None, None, None)
    assert link.exists() and not any(target.iterdir())
    if os.name == "nt":
        link.rmdir()
    else:
        link.unlink()


def test_nested_fsync_and_readback_failures_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _empty_root(tmp_path, "nested-fsync")
    with pytest.raises(ArtifactPublicationError):
        with ArtifactPublication(root) as publication:
            publication.write_bytes("scenario/first.bin", b"first")
            real_sync = publication._sync_child

            def fail_once(name: str) -> None:
                monkeypatch.setattr(publication, "_sync_child", real_sync)
                raise OSError("PRIVATE_CHILD_FSYNC")

            monkeypatch.setattr(publication, "_sync_child", fail_once)
            publication.write_bytes("scenario/second.bin", b"second")
    assert not any(root.iterdir())

    root = _empty_root(tmp_path, "nested-readback")
    with pytest.raises(ArtifactPublicationError):
        with ArtifactPublication(root) as publication:
            publication.write_bytes("scenario/data.bin", b"data")
            monkeypatch.setattr(
                publication,
                "_open_parsed_read",
                lambda _: (_ for _ in ()).throw(OSError("PRIVATE_READ")),
            )
            publication.read_bytes("scenario/data.bin")
    assert not any(root.iterdir())


@pytest.mark.parametrize("failure", ["unlink", "rmdir"])
def test_nested_rollback_primitive_failure_preserves_owned_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    root = _empty_root(tmp_path, f"rollback-{failure}")
    publication = ArtifactPublication(root)
    publication.__enter__()
    publication.write_bytes("scenario/data.bin", b"owned")
    target = root / "scenario" / "data.bin"
    if failure == "unlink":
        real_unlink = publication._unlink_owned_path

        def hostile_unlink(name: str) -> None:
            if name == "scenario/data.bin":
                raise OSError("PRIVATE_UNLINK")
            real_unlink(name)

        monkeypatch.setattr(publication, "_unlink_owned_path", hostile_unlink)
    else:
        real_rmdir = os.rmdir

        def hostile_rmdir(path: Any, *args: Any, **kwargs: Any) -> None:
            if str(path).replace("\\", "/").endswith("scenario"):
                raise OSError("PRIVATE_RMDIR")
            real_rmdir(path, *args, **kwargs)

        monkeypatch.setattr(os, "rmdir", hostile_rmdir)
    with pytest.raises(ArtifactRollbackError) as caught:
        publication.__exit__(None, None, None)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    if failure == "unlink":
        assert target.read_bytes() == b"owned"
    else:
        assert not target.exists() and (root / "scenario").is_dir()


def test_wrong_whole_tree_expectation_rolls_back_every_owned_output(
    tmp_path: Path,
) -> None:
    for index, expected in enumerate(
        (
            {"root.bin"},
            {"root.bin", "scenario/data.bin", "extra.bin"},
            {"root.bin", "scenario/wrong.bin"},
        )
    ):
        root = _empty_root(tmp_path, f"wrong-tree-{index}")
        with pytest.raises(ArtifactPublicationError):
            with ArtifactPublication(root) as publication:
                publication.write_bytes("root.bin", b"root")
                publication.write_bytes("scenario/data.bin", b"nested")
                publication.commit(expected)
        assert not any(root.iterdir())
