"""Vary the fictional workload without changing the independent oracle rules."""
import importlib.util
import json
from pathlib import Path


def generator():
    path=Path(__file__).resolve().parents[1]/'sim/generate.py'
    spec=importlib.util.spec_from_file_location('fictional_seed_generator',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_new_seed_is_reproducible_changes_data_and_keeps_balanced_oracle(tmp_path):
    g=generator();one=g.generate(tmp_path/'one',seed=260117);two=g.generate(tmp_path/'two',seed=260117)
    assert one['seed']==260117 and one['plan_sha256']==two['plan_sha256']
    assert one['days']==30 and one['employees']==15 and one['photos']==300
    assert one['money_events']==3007 and one['new_information']==1500 and one['new_kinds']==4
    original=g.generate(tmp_path/'original')
    assert original['seed']==160030 and one['plan_sha256']!=original['plan_sha256']
    # Original evidence must remain independently reproducible byte for byte.
    assert original['plan_sha256']=='319542324885a17a57cbe5b0bc0d5436b95200ab65829ff60d8436201b9ea54e'
    answers=json.loads((tmp_path/'one/answer-key.json').read_text())
    assert len(answers)==30 and all(a['trial_balance_paise']['debit']==a['trial_balance_paise']['credit']for a in answers)
