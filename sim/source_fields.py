"""Independent exact normalization of documented typed-form source scalars.

Integer amounts mean paise; decimal strings from the UI mean rupees. This does
not alter an approval item or weaken the app's own validators or journal checks.
"""
import copy,re
from decimal import Decimal


def normalise_source_item(item):
    result=copy.deepcopy(item);slots=result.get('after',{}).get('slots',{})
    if 'amount'in slots:
        value=slots['amount']
        if type(value)is int:pass
        elif isinstance(value,str)and re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?',value):slots['amount']=int(Decimal(value)*100)
        else:raise ValueError('Source amount is neither integer paise nor an exact rupee decimal string')
    if 'gst_rate'in slots:
        value=slots['gst_rate']
        if type(value)is int:pass
        elif isinstance(value,str)and re.fullmatch(r'[0-9]+',value):slots['gst_rate']=int(value)
        elif type(value)is float and value.is_integer():slots['gst_rate']=int(value)
        else:raise ValueError('Source GST rate is not an integer percentage')
    return result
