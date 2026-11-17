"""Same-build monthly runs need an independent real-code upgrade proof."""
import copy,importlib.util
from pathlib import Path
import pytest


def verifier():
    p=Path(__file__).resolve().parents[1]/'sim/artifact_proof.py'
    s=importlib.util.spec_from_file_location('fictional_artifact_proof',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def proof():
    target={'version':'0.16.11','source_sha256':'b'*64,'source_files':108}
    source={'version':'0.16.10','source_sha256':'a'*64,'source_files':106}
    expected={'version':'0.16.11','build':target,'image_id':'sha256:'+'c'*64}
    p={'kind':'actual_version_upgrade','passed':True,'source_version':'0.16.10','target_version':'0.16.11',
       'source_build':source,'source_bundle_build':source,'target_build':target,
       'source_image_id':'sha256:'+'d'*64,'target_image_id':expected['image_id'],
       'source_review_bundle_sha256':'e'*64,'database_backend':'postgresql','restricted_app_role':True,'changed_code_files':['studioos/finance_intake.py'],
       'upgrade':{'baseline':'0.16.10','candidate':'0.16.11','passed':True,'restore_copy_identical':True,
                  'test_upgrade_identical':True,'live_upgrade_identical':True,'rollback_identical':True,
                  'restore_copy_opened':{'real_http_app_opened':True},'masked_copy_opened':{'old_photo_opened':True},
                  'old_records_opened':{'old_photo_opened':True},'old_record_editable':{'original_values_restored':True,'new_history_preserved':True,'approved_revision_tickets':[41,42]}}}
    return p,expected


def test_exact_artifact_accepts_only_real_distinct_version_and_code_proof():
    m=verifier();p,e=proof();assert m.validate(p,e)['source_version']=='0.16.10'
    for field in ('restore_copy_identical','test_upgrade_identical','live_upgrade_identical','rollback_identical'):
        bad=copy.deepcopy(p);bad['upgrade'][field]=False
        with pytest.raises(ValueError):m.validate(bad,e)
    bad=copy.deepcopy(p);bad['changed_code_files']=['VERSION','studioos/main.py','studioos/static/index.html']
    with pytest.raises(ValueError):m.validate(bad,e)
    bad=copy.deepcopy(p);bad['source_version']=bad['target_version']
    with pytest.raises(ValueError):m.validate(bad,e)


def test_mismatched_shipping_image_source_or_prior_bundle_is_rejected():
    m=verifier();p,e=proof()
    for key,value in [('target_image_id','sha256:'+'f'*64),('target_build',{**p['target_build'],'source_sha256':'f'*64}),
                      ('source_bundle_build',{**p['source_build'],'source_sha256':'f'*64}),('source_image_id',p['target_image_id'])]:
        bad=copy.deepcopy(p);bad[key]=value
        with pytest.raises(ValueError):m.validate(bad,e)
