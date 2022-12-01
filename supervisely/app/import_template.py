from typing import Optional, Union
from supervisely._utils import is_production
import supervisely.io.env as env
from supervisely.api.api import Api
from supervisely.app import get_data_dir
from os.path import join, basename
from pathlib import Path


try:
    from typing import Literal
except ImportError:
    # for compatibility with python 3.7
    from typing_extensions import Literal


class Import:
    def process(
        self, workspace_id: int, project_id: int, dataset_id: int, path: str, is_directory: bool
    ) -> Optional[Union[int, None]]:
        raise NotImplementedError() # implement your own method when inherit

    def run(self):
        api = Api.from_env()
        task_id = None
        if is_production():
            task_id = env.task_id()

        team_id = env.team_id()
        workspace_id = env.workspace_id()
          
        file = env.file(raise_not_found=False)
        folder = env.folder(raise_not_found=False)

        if file is not None and folder is not None:
            raise KeyError(
                "Both FILE and FOLDER envs are defined, but only one is allowed for the import"
            )
        if file is None and folder is None:
            raise KeyError(
                "One of the environment variables has to be defined for the import app: FILE or FOLDER"
            )

        is_directory = True
        path = folder
        if file is not None:
            path = file
            is_directory = False
            
        project_id = env.project_id(raise_not_found=False)
        dataset_id = env.dataset_id(raise_not_found=False)
        
        # get or create project with the same name as input file and empty dataset in it
        if project_id is None:
            project_name = Path(path).stem
            project = api.project.create(workspace_id=workspace_id, name=project_name, change_name_if_conflict=True)
        else:
            project = api.project.get_info_by_id(id=project_id)
        print(f"Working project: id={project.id}, name={project.name}")
            
        if dataset_id is None: 
            dataset = api.dataset.create(project_id=project.id, name="dataset", change_name_if_conflict=True)
        else:
            dataset = api.dataset.get_info_by_id(id=dataset_id)
        print(f"Working dataset: id={dataset.id}, name={dataset.name}")

        if is_production():
            local_save_path = join(get_data_dir(), basename(path))
            if is_directory:
                raise NotImplementedError()
                # api.file.download_directory(team_id=team_id, remote_path=path, local_save_path=local_save_path)
            else:
                api.file.download(team_id=team_id, remote_path=path, local_save_path=local_save_path)
            path = local_save_path
            
        project_id = self.process(workspace_id=workspace_id, project_id=project.id, dataset_id=dataset.id, path=path, is_directory=is_directory)
        if type(project_id) is int and is_production():
            info = api.project.get_info_by_id(project_id)
            api.task.set_output_project(task_id=task_id, project_id=info.id, project_name=info.name)
            print(f"Result project: id={info.id}, name={info.name}")
