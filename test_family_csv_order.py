from types import SimpleNamespace

import pytest

from family_csv import add_diff


@pytest.mark.parametrize(('before_order','after_order'), [('1',1),(1,'1')])
def test_mixed_order_types_do_not_create_false_guardian_changes(before_order,after_order):
    result=SimpleNamespace(changes=[])
    add_diff(result,2,'family',1,
      {'guardians_data':[{'order':before_order,'last_name':'架空','parent_account_id':7}]},
      {'guardians_data':[{'order':after_order,'last_name':'架空','parent_account_id':7}]})
    assert result.changes==[]


def test_mixed_order_types_keep_the_changed_field_on_the_correct_guardian():
    result=SimpleNamespace(changes=[])
    add_diff(result,2,'family',1,
      {'guardians_data':[{'order':'1','last_name':'架空A','phone':'111'}, {'order':2,'last_name':'架空B','phone':'222'}]},
      {'guardians_data':[{'order':1,'last_name':'架空A','phone':'333'}, {'order':'2','last_name':'架空B','phone':'222'}]})
    assert len(result.changes)==1
    assert result.changes[0]['field']=='保護者1 電話番号'
    assert (result.changes[0]['before'],result.changes[0]['after'])==('111','333')
