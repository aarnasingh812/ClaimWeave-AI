from app.agent.workflow import verify_policy, check_documents, validate_claim

def test_policy_mismatch_blocks():
    result = verify_policy({'insurer':'Example Insurance','policy_name':'Plan A',
                            'policy_extraction':{'insurer':'Other','policy_name':'Plan A'}})
    assert result['policy_verified'] is False

def test_missing_document():
    result = check_documents({'planned_requirements': [{
        'name':'Hospital bill','category':'document','mandatory':True,
        'canonical_document_type':'hospital_bill','needs_user_confirmation':False
    }], 'extracted_documents': []})
    assert result['document_check']['missing'] == ['Hospital bill']

def test_conditional_document_requires_confirmation():
    result = check_documents({'planned_requirements': [{
        'name':'FIR','category':'document','mandatory':True,
        'canonical_document_type':'fir_mlc','needs_user_confirmation':True
    }], 'extracted_documents': []})
    assert result['document_check']['needs_confirmation'] == ['FIR']

def test_validation_blocks_missing():
    result = validate_claim({'policy_verified':True,'planned_requirements':[{'name':'Bill'}],
        'document_check':{'missing':['Bill'],'needs_confirmation':[]},'warnings':[]})
    assert result['validation']['passed'] is False
