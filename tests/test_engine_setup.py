import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import engine_setup


class EngineSetupTests(unittest.TestCase):
    def test_valid_packaged_model_skips_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'nested'/'model.bin'
            target.parent.mkdir(parents=True);target.write_bytes(b'packaged-model')
            digest=hashlib.sha256(target.read_bytes()).hexdigest()
            (root/'installed.json').write_text(json.dumps({
                'repo':'example/model','revision':'fixed',
                'files':[{'file':'nested/model.bin','size':target.stat().st_size,'sha256':digest}],
            }),encoding='utf-8')
            with patch.object(engine_setup.requests,'get') as request:
                engine_setup.model('example/model','fixed',root,['nested/model.bin'])
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
