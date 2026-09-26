import unittest
from chatgpt_operation.controller.reasoning_provider import (
    ProviderUnavailable,ReasoningProviderRegistry,
)


class FakeProvider:
    name="fake"
    def reason(self,*,task,context,attempt,validation_error):
        return {"task":task,"attempt":attempt}


class ReasoningProviderTests(unittest.TestCase):
    def test_missing_provider_is_explicitly_unavailable(self):
        registry=ReasoningProviderRegistry()
        self.assertFalse(registry.status().available)
        with self.assertRaises(ProviderUnavailable):
            registry.runner()

    def test_configured_provider_adapts_to_reasoning_runner(self):
        registry=ReasoningProviderRegistry(FakeProvider())
        self.assertTrue(registry.status().available)
        self.assertEqual(registry.runner()("x",{},1,None),{"task":"x","attempt":1})


if __name__=="__main__":
    unittest.main()
