import importlib
import unittest


class ImportTests(unittest.TestCase):
    def test_server_module_imports(self):
        module = importlib.import_module("illustrator.server")
        self.assertTrue(callable(module.main))

    def test_cli_exposes_run_server(self):
        module = importlib.import_module("illustrator.cli")
        self.assertTrue(callable(module.run_server))

    def test_platform_backend_imports(self):
        module = importlib.import_module("illustrator.platform_backend")
        self.assertTrue(callable(module.get_backend))
        self.assertTrue(hasattr(module, "IllustratorBackend"))
        self.assertTrue(hasattr(module, "MacBackend"))
        self.assertTrue(hasattr(module, "WindowsBackend"))

    def test_prompt_module_imports(self):
        module = importlib.import_module("illustrator.prompt")
        self.assertTrue(callable(module.get_system_prompt))
        self.assertTrue(callable(module.get_prompt_suggestions))

    def test_vectorizer_module_imports(self):
        module = importlib.import_module("illustrator.vectorizer")
        self.assertTrue(callable(module.vectorize_bitmap))
        self.assertTrue(callable(module.vectorize_icon_silhouette))
        self.assertTrue(callable(module.generate_illustrator_jsx))

    def test_image_trace_module_imports(self):
        module = importlib.import_module("illustrator.image_trace")
        self.assertTrue(callable(module.prepare_image_trace_source))
        self.assertTrue(callable(module.generate_image_trace_jsx))

    def test_vectorize_cli_imports(self):
        module = importlib.import_module("illustrator.vectorize_cli")
        self.assertTrue(callable(module.main))

    def test_visual_layers_module_imports(self):
        module = importlib.import_module("illustrator.visual_layers")
        self.assertTrue(callable(module.apply_visual_layer_plan))


if __name__ == "__main__":
    unittest.main()
