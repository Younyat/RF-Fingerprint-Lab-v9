import test from 'node:test';import assert from 'node:assert/strict';
import {summarizeExamples,splitHasLeakage} from '../.ble-validation/datasetStudioModel.js';
test('dataset summary keeps included and quarantined examples separate',()=>{const result=summarizeExamples([{session_id:'s1',crc_valid:true,inclusion_state:'INCLUDED_STRONG'},{session_id:'s1',crc_valid:false,inclusion_state:'EXCLUDED_OVERFLOW'}]);assert.deepEqual(result,{total:2,crcValid:1,included:1,excluded:1,sessions:1})});
test('group split detects session leakage',()=>{assert.equal(splitHasLeakage({train:{s1:['a']},validation:{s2:['b']},test:{s1:['c']}}),true);assert.equal(splitHasLeakage({train:{s1:['a']},validation:{s2:['b']},test:{s3:['c']}}),false)});
