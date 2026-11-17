"""A release context must match source verbatim, never a relabelled baseline."""
import importlib.util
from pathlib import Path
import pytest
from studioos.build_identity import source_identity


def builder():
    path=Path(__file__).resolve().parents[1]/'sim/build_release.py'
    spec=importlib.util.spec_from_file_location('fictional_clean_build',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def source(tmp_path):
    root=tmp_path/'source';(root/'studioos').mkdir(parents=True);(root/'agents').mkdir()
    (root/'VERSION').write_text('0.16.11\n');(root/'requirements.txt').write_text('fictional-dependency==1\n')
    (root/'Dockerfile').write_text('FROM fictional-test-only\n');(root/'.dockerignore').write_text('data/\n')
    (root/'studioos/app.py').write_text('APP_VERSION="0.16.11"\n')
    (root/'operator.example').write_text('Fictional configuration outside the image')
    (root/'data').mkdir();(root/'data/fictional-row.txt').write_text('Never copy data into a build')
    return root


def test_clean_context_preserves_exact_version_and_source_and_excludes_data(tmp_path):
    root=source(tmp_path);m=builder();context=tmp_path/'context'
    identity=m.prepare_context(root,context)
    assert identity==source_identity(root)==source_identity(context)
    assert (context/'VERSION').read_text()=='0.16.11\n'
    assert (context/'studioos/app.py').read_bytes()==(root/'studioos/app.py').read_bytes()
    assert not(context/'data').exists()and not(context/'operator.example').exists()


def test_changed_or_relabelled_context_is_rejected(tmp_path):
    root=source(tmp_path);m=builder();context=tmp_path/'context';identity=m.prepare_context(root,context)
    (context/'VERSION').write_text('0.16.10\n')
    with pytest.raises(ValueError,match='identity'):m.verify_context(context,identity)
