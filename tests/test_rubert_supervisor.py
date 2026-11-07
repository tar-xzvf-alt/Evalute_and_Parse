from argparse import Namespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.train_rubert_pair import supervise


class SupervisorTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        runtime = root / 'runtime'; runtime.mkdir()
        (runtime / '.parsevk-training-root').write_text('test')
        python = runtime / '.venv-rubert/Scripts/python.exe'
        python.parent.mkdir(parents=True); python.write_text('test placeholder')
        (runtime / 'outputs').mkdir()
        project = root / 'project'; (project / 'dataset').mkdir(parents=True)
        (project / 'dataset/manifest.json').write_text('{}')
        return Namespace(project=str(project), runtime_root=str(runtime),
                         run_dir=str(runtime / 'outputs/run1'), source_commit='test')

    def test_success_is_sequential_offline_with_completion_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(directory)
            def spawn(command, **kwargs):
                task = command[command.index('--task') + 1]
                self.assertEqual(task, 'A' if spawn.calls == 0 else 'B')
                self.assertEqual(kwargs['env']['HF_HUB_OFFLINE'], '1')
                self.assertEqual(command[command.index('--max-length') + 1], '512')
                output = Path(command[command.index('--output') + 1])
                def finish():
                    output.mkdir(); (output / 'completed.json').write_text('{}')
                    return 0
                spawn.calls += 1
                return Mock(pid=123, wait=Mock(side_effect=finish))
            spawn.calls = 0
            with patch('scripts.train_rubert_pair.subprocess.Popen', side_effect=spawn):
                self.assertEqual(supervise(args), 0)
            status = json.loads((Path(args.run_dir) / 'status.json').read_text())
            self.assertEqual(status['status'], 'completed')
            self.assertEqual([t['task'] for t in status['tasks']], ['A', 'B'])

    def test_first_failure_stops_without_retry_or_second_model(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(directory)
            with patch('scripts.train_rubert_pair.subprocess.Popen', return_value=Mock(pid=123, wait=Mock(return_value=1))) as spawn:
                self.assertEqual(supervise(args), 1)
                self.assertEqual(spawn.call_count, 1)
            status = json.loads((Path(args.run_dir) / 'status.json').read_text())
            self.assertEqual(status['status'], 'failed')
            self.assertEqual(len(status['tasks']), 1)

    def test_existing_run_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(directory)
            Path(args.run_dir).mkdir()
            with self.assertRaises(FileExistsError):
                supervise(args)

    def test_explicit_b_only_balanced_run_does_not_repeat_a(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(directory); args.tasks = ['B']; args.balance_topics = True
            def spawn(command, **kwargs):
                self.assertEqual(command[command.index('--task') + 1], 'B')
                self.assertIn('--balance-topics', command)
                output = Path(command[command.index('--output') + 1])
                def finish():
                    output.mkdir(); (output / 'completed.json').write_text('{}')
                    return 0
                return Mock(pid=123, wait=Mock(side_effect=finish))
            with patch('scripts.train_rubert_pair.subprocess.Popen', side_effect=spawn) as calls:
                self.assertEqual(supervise(args), 0)
                self.assertEqual(calls.call_count, 1)


if __name__ == '__main__':
    unittest.main()
