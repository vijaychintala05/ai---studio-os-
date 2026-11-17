"""A recorded month must prove actual positive replay, not quiet offline fallback."""


def configuration(data):
    settings=data.get('settings')or{};status=data.get('status')or{}
    if not (settings.get('enabled')is True and settings.get('provider')=='recorded'
            and settings.get('model')=='studioos-recorded-reader-v1'
            and settings.get('masking')is True and settings.get('few_shot')is False
            and status.get('on')is True and status.get('paid_server_switch')is False
            and status.get('mode')=='recorded_fixture_replay'):
        raise ValueError('Recorded month requires verified replay on, masking on, fixed prompts and paid providers off')


def compare(before,after,expected_calls):
    failures=[];delta={}
    def fail(reason):failures.append({'severity':'HIGH','kind':'recorded_model_coverage','error':reason})
    if type(expected_calls)is not int or expected_calls<=0:fail('Expected positive captured chat-model calls')
    for key in ('transport_attempts','transport_replayed','nonempty_replies','gateway_ok'):
        old,new=before.get(key),after.get(key)
        if type(old)is not int or type(new)is not int or new<old:
            fail(key+' is missing or moved backwards');delta[key]=None
        else:
            delta[key]=new-old
            if delta[key]!=expected_calls:fail(key+' does not match the captured daily workload')
    for key in ('transport_failures','gateway_invalid','gateway_other_failures','network_calls','paid_provider_gateway_rows'):
        if before.get(key)!=0 or after.get(key)!=0:fail(key+' must stay zero')
    for sample in (before,after):
        if sample.get('paid_server_switch')is not False or sample.get('mode')!='recorded_fixture_replay':
            fail('Recorded mode and paid-off evidence missing')
    return {'passed':not failures,'expected_calls':expected_calls,'delta':delta,
            'after':after,'failures':failures,'inference':'synthetic recorded replies; no fresh provider accuracy claim'}
