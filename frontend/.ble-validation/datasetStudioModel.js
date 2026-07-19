export const summarizeExamples = (examples) => ({
    total: examples.length,
    crcValid: examples.filter(item => item.crc_valid).length,
    included: examples.filter(item => item.inclusion_state?.startsWith('INCLUDED')).length,
    excluded: examples.filter(item => item.inclusion_state?.startsWith('EXCLUDED')).length,
    sessions: new Set(examples.map(item => item.session_id).filter(Boolean)).size,
});
export const splitHasLeakage = (split) => {
    const groups = [Object.keys(split.train), Object.keys(split.validation), Object.keys(split.test)];
    return groups.some((left, index) => groups.some((right, rightIndex) => rightIndex > index && left.some(key => right.includes(key))));
};
