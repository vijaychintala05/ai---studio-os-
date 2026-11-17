"""Fail-closed eligibility for a month entirely on the exact shipping artifact.

An independent populated actual-version upgrade and rollback must already pass.
The old distinct-version checkpoint remains the default for historical runs.
"""
import re


def validate(proof, expected):
    def require(condition, message):
        if not condition:raise ValueError('Exact-artifact upgrade proof: '+message)
    require(proof.get('kind')=='actual_version_upgrade'and proof.get('passed')is True,'actual upgrade not passed')
    source,target=proof.get('source_version'),proof.get('target_version')
    require(source!=target and target==expected['version'],'versions are not a real distinct upgrade')
    require(proof.get('database_backend')=='postgresql'and proof.get('restricted_app_role')is True,'restricted PostgreSQL proof required')
    require(proof.get('target_build')==expected['build'],'shipping source identity mismatch')
    require(proof.get('target_image_id')==expected['image_id'],'shipping image identity mismatch')
    require(proof.get('source_build')==proof.get('source_bundle_build'),'prior image differs from its review bundle')
    require((proof.get('source_build')or{}).get('version')==source,'prior source version mismatch')
    for build in (proof.get('source_build')or{},proof.get('target_build')or{}):
        require(bool(re.fullmatch(r'[0-9a-f]{64}',str(build.get('source_sha256','')))),'missing source SHA')
    require(proof['source_build']['source_sha256']!=proof['target_build']['source_sha256'],'same source is not an upgrade')
    for key in ('source_image_id','target_image_id'):
        require(bool(re.fullmatch(r'sha256:[0-9a-f]{64}',str(proof.get(key,'')))),'invalid image ID')
    require(proof['source_image_id']!=proof['target_image_id'],'same image is not an upgrade')
    require(bool(re.fullmatch(r'[0-9a-f]{64}',str(proof.get('source_review_bundle_sha256','')))),'missing prior bundle SHA')
    labels={'studioos/main.py','studioos/static/index.html'}
    changed=proof.get('changed_code_files',[])
    require(any(isinstance(name,str)and name.startswith('studioos/')and name.endswith('.py')
                and name not in labels and '..'not in name.split('/')for name in changed),'label-only changes are not an upgrade')
    upgrade=proof.get('upgrade')or{}
    require(upgrade.get('baseline')==source and upgrade.get('candidate')==target,'checkpoint versions mismatch')
    for field in ('passed','restore_copy_identical','test_upgrade_identical','live_upgrade_identical','rollback_identical'):
        require(upgrade.get(field)is True,field+' missing or failed')
    require((upgrade.get('restore_copy_opened')or{}).get('real_http_app_opened')is True,'populated restore not opened')
    for field in ('masked_copy_opened','old_records_opened'):
        require((upgrade.get(field)or{}).get('old_photo_opened')is True,field+' missing')
    edited=upgrade.get('old_record_editable')or{}
    require(edited.get('original_values_restored')is True and edited.get('new_history_preserved')is True,'old record edit not verified')
    tickets=edited.get('approved_revision_tickets',[])
    require(len(tickets)==2 and len(set(tickets))==2 and all(type(x)is int and x>0 for x in tickets),'old edit approval evidence missing')
    return proof
