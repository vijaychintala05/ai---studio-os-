"""Replacing a TEST dataset must retain old proof and require fresh backup proof."""
import json
import pytest
from studioos import safekeeping as S


def fixture(tmp_path,environment='test'):
    cfg=S.Config({'STUDIOOS_ENV':environment,'STUDIOOS_BACKUP_DIR':str(tmp_path/'test-primary')})
    source=tmp_path/'studioos_20260115T000000Z.dump';source.write_bytes(b'FICTIONAL verified source')
    S.write_status(cfg,last_backup={'file':'old-test.dump','verified':True},last_drill={'ok':True},chain_anchors=[{'file':'old-test.dump','heads':{'audit_events':{'id':12,'hash':'old-dataset-hash'}}}])
    return cfg,source


def test_refresh_archives_old_proof_and_requires_a_new_verified_backup(tmp_path):
    cfg,source=fixture(tmp_path);old=(cfg.status_dir/'status.json').read_bytes()
    proof=S.reset_masked_copy_status(cfg,source)
    assert proof['source_sha256']==S.sha256_of(source)
    assert proof['requires_verified_backup']is True
    archive=cfg.status_dir/proof['previous_status_archive'];assert archive.read_bytes()==old
    new=S.read_status(cfg)
    assert new['chain_anchors']==[] and new['last_backup']is None and new['last_drill']is None
    assert new['masked_test_copy']==proof
    from studioos.data_safety import health
    assert health(new,S.now(),'test')['overall']=='fail','An old green status must not protect a new dataset'


def test_status_reset_is_impossible_outside_test(tmp_path):
    cfg,source=fixture(tmp_path,'production');old=(cfg.status_dir/'status.json').read_bytes()
    with pytest.raises(S.SafekeepingError,match='test environment'):S.reset_masked_copy_status(cfg,source)
    assert (cfg.status_dir/'status.json').read_bytes()==old


def test_repeated_refreshes_keep_distinct_previous_status_archives(tmp_path):
    cfg,source=fixture(tmp_path);a=S.reset_masked_copy_status(cfg,source);b=S.reset_masked_copy_status(cfg,source)
    assert a['previous_status_archive']!=b['previous_status_archive']
    for proof in (a,b):assert (cfg.status_dir/proof['previous_status_archive']).is_file()
    assert json.loads((cfg.status_dir/b['previous_status_archive']).read_text())['masked_test_copy']==a
