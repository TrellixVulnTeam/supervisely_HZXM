# coding: utf-8

import io
from collections import defaultdict
import urllib.parse

from supervisely_lib.api.module_api import ApiField, RemoveableBulkModuleApi
from supervisely_lib.imaging import image as sly_image
from supervisely_lib.io.fs import ensure_base_path, get_file_hash, get_file_ext, get_file_name
from supervisely_lib._utils import batched, generate_free_name
from requests_toolbelt import MultipartDecoder, MultipartEncoder
import re


class ImageApi(RemoveableBulkModuleApi):
    @staticmethod
    def info_sequence():
        return [ApiField.ID,
                ApiField.NAME,
                ApiField.LINK,
                ApiField.HASH,
                ApiField.MIME,
                ApiField.EXT,
                ApiField.SIZE,
                ApiField.WIDTH,
                ApiField.HEIGHT,
                ApiField.LABELS_COUNT,
                ApiField.DATASET_ID,
                ApiField.CREATED_AT,
                ApiField.UPDATED_AT,
                ApiField.META]

    @staticmethod
    def info_tuple_name():
        return 'ImageInfo'

    def get_list(self, dataset_id, filters=None):
        '''
        :param dataset_id: int
        :param filters: list
        :return: list all the images for a given dataset
        '''
        return self.get_list_all_pages('images.list',  {ApiField.DATASET_ID: dataset_id, ApiField.FILTER: filters or []})

    def get_info_by_id(self, id):
        '''
        :param id: int
        :return: image metadata by numeric id
        '''
        return self._get_info_by_id(id, 'images.info')

    # @TODO: reimplement to new method images.bulk.info
    def get_info_by_id_batch(self, ids):
        '''
        :param ids: list of integers
        :return: list of images metadata
        '''
        results = []
        if len(ids) == 0:
            return results
        dataset_id = self.get_info_by_id(ids[0]).dataset_id
        for batch in batched(ids):
            filters = [{"field": ApiField.ID, "operator": "in", "value": batch}]
            results.extend(self.get_list_all_pages('images.list', {ApiField.DATASET_ID: dataset_id,
                                                                   ApiField.FILTER: filters}))
        temp_map = {info.id: info for info in results}
        ordered_results = [temp_map[id] for id in ids]
        return ordered_results

    def _download(self, id, is_stream=False):
        '''
        :param id: int
        :param is_stream: bool
        :return: Response class object contain metadata of image with given id
        '''
        response = self._api.post('images.download', {ApiField.ID: id}, stream=is_stream)
        return response

    def download_np(self, id):
        '''
        Download image with given id in numpy format
        :param id: int
        :return: image in RGB format(numpy matrix)
        '''
        response = self._download(id)
        img = sly_image.read_bytes(response.content)
        return img

    def download_path(self, id, path):
        '''
        Download image with given id and saves it for a given path
        :param id: int
        :param path: str
        '''
        response = self._download(id, is_stream=True)
        ensure_base_path(path)
        with open(path, 'wb') as fd:
            for chunk in response.iter_content(chunk_size=1024*1024):
                fd.write(chunk)

    def _download_batch(self, dataset_id, ids):
        '''
        Generate image id and it content from given dataset and list of images ids
        :param dataset_id: int
        :param ids: list of integers
        '''
        for batch_ids in batched(ids):
            response = self._api.post(
                'images.bulk.download', {ApiField.DATASET_ID: dataset_id, ApiField.IMAGE_IDS: batch_ids})
            decoder = MultipartDecoder.from_response(response)
            for part in decoder.parts:
                content_utf8 = part.headers[b'Content-Disposition'].decode('utf-8')
                # Find name="1245" preceded by a whitespace, semicolon or beginning of line.
                # The regex has 2 capture group: one for the prefix and one for the actual name value.
                img_id = int(re.findall(r'(^|[\s;])name="(\d*)"', content_utf8)[0][1])
                yield img_id, part

    def download_paths(self, dataset_id, ids, paths, progress_cb=None):
        '''
        Download images with given ids and saves it for a given paths
        :param dataset_id: int
        :param ids: list of integers
        :param paths: list of str (if ids list != lengh of paths list raise error)
        :param progress_cb:
        '''
        if len(ids) == 0:
            return
        if len(ids) != len(paths):
            raise RuntimeError("Can not match \"ids\" and \"paths\" lists, len(ids) != len(paths)")

        id_to_path = {id: path for id, path in zip(ids, paths)}
        #debug_ids = []
        for img_id, resp_part in self._download_batch(dataset_id, ids):
            #debug_ids.append(img_id)
            with open(id_to_path[img_id], 'wb') as w:
                w.write(resp_part.content)
            if progress_cb is not None:
                progress_cb(1)
        #if ids != debug_ids:
        #    raise RuntimeError("images.bulk.download: imageIds order is broken")

    def download_bytes(self, dataset_id, ids, progress_cb=None):
        '''
        Doenload images with given ids from dataset with given id in binary format(bytes)
        :param dataset_id: int
        :param ids: list of integers
        :param progress_cb:
        :return: list of images in binary format
        '''
        if len(ids) == 0:
            return []

        id_to_img = {}
        for img_id, resp_part in self._download_batch(dataset_id, ids):
            id_to_img[img_id] = resp_part.content
            if progress_cb is not None:
                progress_cb(1)

        return [id_to_img[id] for id in ids]

    def download_nps(self, dataset_id, ids, progress_cb=None):
        '''
        Doenload images with given ids from dataset with given id in numpy format
        :param dataset_id: int
        :param ids: list of integers
        :param progress_cb:
        :return: list of images in RGB format(numpy matrix)
        '''
        return [sly_image.read_bytes(img_bytes)
                for img_bytes in self.download_bytes(dataset_id=dataset_id, ids=ids, progress_cb=progress_cb)]

    def check_existing_hashes(self, hashes):
        '''
        :param hashes: list of str
        :return: list of jsons objects(None if image with given hash not exist)
        '''
        results = []
        if len(hashes) == 0:
            return results
        for hashes_batch in batched(hashes, batch_size=900):
            response = self._api.post('images.internal.hashes.list', hashes_batch)
            results.extend(response.json())
        return results

    def check_image_uploaded(self, hash):
        '''
        :param hash: str
        :return: True if image with given hash exist, False in over way
        '''
        response = self._api.post('images.internal.hashes.list', [hash])
        results = response.json()
        if len(results) == 0:
            return False
        else:
            return True

    def _upload_data_bulk(self, func_item_to_byte_stream, func_item_hash, items, progress_cb):
        hashes = []
        if len(items) == 0:
            return hashes

        hash_to_items = defaultdict(list)

        for idx, item in enumerate(items):
            item_hash = func_item_hash(item)
            hashes.append(item_hash)
            hash_to_items[item_hash].append(item)

        unique_hashes = set(hashes)
        remote_hashes = self.check_existing_hashes(list(unique_hashes))
        new_hashes = unique_hashes - set(remote_hashes)

        if progress_cb is not None:
            progress_cb(len(remote_hashes))

        # upload only new images to supervisely server
        items_to_upload = []
        for hash in new_hashes:
            items_to_upload.extend(hash_to_items[hash])

        for batch in batched(items_to_upload):
            content_dict = {}
            for idx, item in enumerate(batch):
                content_dict["{}-file".format(idx)] = (str(idx), func_item_to_byte_stream(item), 'image/*')
            encoder = MultipartEncoder(fields=content_dict)
            self._api.post('images.bulk.upload', encoder)
            if progress_cb is not None:
                progress_cb(len(batch))

        return hashes

    def upload_path(self, dataset_id, name, path, meta=None):
        '''
        Upload image with given name from given path to dataset
        :param dataset_id: int
        :param name: str
        :param path: str
        :param meta:
        :return: list of images
        '''
        metas = None if meta is None else [meta]
        return self.upload_paths(dataset_id, [name], [path], metas=metas)[0]

    def upload_paths(self, dataset_id, names, paths, progress_cb=None, metas=None):
        '''
        Upload images with given names from given pathes to dataset
        :param dataset_id: int
        :param names: list of str (if lengh of names list != lengh of paths list raise error)
        :param paths: list of str
        :param progress_cb:
        :param metas: list of str
        :return: list of images
        '''
        def path_to_bytes_stream(path):
            return open(path, 'rb')
        hashes = self._upload_data_bulk(path_to_bytes_stream, get_file_hash, paths, progress_cb)
        return self.upload_hashes(dataset_id, names, hashes, metas=metas)

    def upload_np(self, dataset_id, name, img, meta=None):
        '''
        Upload given image in numpy with given name to dataset
        :param dataset_id: int
        :param name: str
        :param img: image in RGB format(numpy matrix)
        :param meta:
        :return: list of images
        '''
        metas = None if meta is None else [meta]
        return self.upload_nps(dataset_id, [name], [img], metas=metas)[0]

    def upload_nps(self, dataset_id, names, imgs, progress_cb=None, metas=None):
        '''
        Upload given images in numpy with given names to dataset
        :param dataset_id: int
        :param names: list of str (if lengh of names list != lengh of imgs list raise error)
        :param imgs: list of numpy matrix
        :param progress_cb:
        :param metas:
        :return: list of images
        '''
        def img_to_bytes_stream(item):
            img, name = item[0], item[1]
            img_bytes = sly_image.write_bytes(img, get_file_ext(name))
            return io.BytesIO(img_bytes)

        def img_to_hash(item):
            img, name = item[0], item[1]
            return sly_image.get_hash(img, get_file_ext(name))

        img_name_list = list(zip(imgs, names))
        hashes = self._upload_data_bulk(img_to_bytes_stream, img_to_hash, img_name_list, progress_cb)
        return self.upload_hashes(dataset_id, names, hashes, metas=metas)

    def upload_link(self, dataset_id, name, link, meta=None):
        '''
        Upload image from given link with given name to dataset
        :param dataset_id: int
        :param name: str
        :param link: str
        :param meta:
        :return: list of images
        '''
        metas = None if meta is None else [meta]
        return self.upload_links(dataset_id, [name], [link], metas=metas)[0]

    def upload_links(self, dataset_id, names, links, progress_cb=None,  metas=None):
        '''
        Upload images from given links with given names to dataset
        :param dataset_id: int
        :param names: list of str (if lengh of names list != lengh of links list raise error)
        :param links: list of str
        :param progress_cb:
        :param metas:
        :return: list of images
        '''
        return self._upload_bulk_add(lambda item: (ApiField.LINK, item), dataset_id, names, links, progress_cb, metas=metas)

    def upload_hash(self, dataset_id, name, hash, meta=None):
        '''
        Upload image from given hash with given name to dataset
        :param dataset_id: int
        :param name: str
        :param hash: str
        :param meta:
        :return: list of images
        '''
        metas = None if meta is None else [meta]
        return self.upload_hashes(dataset_id, [name], [hash], metas=metas)[0]

    def upload_hashes(self, dataset_id, names, hashes, progress_cb=None,  metas=None):
        '''
        Upload images from given hashes with given names to dataset
        :param dataset_id: int
        :param names: list of str (if lengh of names list != lengh of hashes list raise error)
        :param hashes: list of str
        :param progress_cb:
        :param metas:
        :return: list of images
        '''
        return self._upload_bulk_add(lambda item: (ApiField.HASH, item), dataset_id, names, hashes, progress_cb, metas=metas)

    def upload_id(self, dataset_id, name, id, meta=None):
        '''
        Upload image from given id with given name to dataset
        :param dataset_id: int
        :param name: str
        :param id: int
        :param meta:
        :return: list of images
        '''
        metas = None if meta is None else [meta]
        return self.upload_ids(dataset_id, [name], [id], metas=metas)[0]

    def upload_ids(self, dataset_id, names, ids, progress_cb=None, metas=None):
        '''
        Upload images from given ids with given names to dataset
        :param dataset_id: int
        :param names: list of str (if lengh of names list != lengh of ids list raise error)
        :param ids: list of integers (all ids have to be from single dataset)
        :param progress_cb:
        :param metas:
        :return: list of images
        '''
        # all ids have to be from single dataset
        infos = self.get_info_by_id_batch(ids)
        hashes = [info.hash for info in infos]
        return self.upload_hashes(dataset_id, names, hashes, progress_cb, metas=metas)

    def _upload_bulk_add(self, func_item_to_kv, dataset_id, names, items, progress_cb=None, metas=None):
        results = []

        if len(names) == 0:
            return results
        if len(names) != len(items):
            raise RuntimeError("Can not match \"names\" and \"items\" lists, len(names) != len(items)")

        if metas is None:
            metas = [{}] * len(names)
        else:
            if len(names) != len(metas):
                raise RuntimeError("Can not match \"names\" and \"metas\" len(names) != len(metas)")

        for batch in batched(list(zip(names, items, metas))):
            images = []
            for name, item, meta in batch:
                item_tuple = func_item_to_kv(item)
                #@TODO: 'title' -> ApiField.NAME
                image_data = {'title': name, item_tuple[0]: item_tuple[1]}
                if len(meta) != 0 and type(meta) == dict:
                    image_data[ApiField.META] = meta
                images.append(image_data)

            response = self._api.post('images.bulk.add', {ApiField.DATASET_ID: dataset_id, ApiField.IMAGES: images})
            if progress_cb is not None:
                progress_cb(len(images))

            for info_json in response.json():
                info_json_copy = info_json.copy()
                info_json_copy[ApiField.EXT] = info_json[ApiField.MIME].split('/')[1]
                #results.append(self.InfoType(*[info_json_copy[field_name] for field_name in self.info_sequence()]))
                results.append(self._convert_json_info(info_json_copy))

        #name_to_res = {img_info.name: img_info for img_info in results}
        #ordered_results = [name_to_res[name] for name in names]

        return results #ordered_results

    #@TODO: reimplement
    def _convert_json_info(self, info: dict, skip_missing=True):
        if info is None:
            return None
        temp_ext = None
        field_values = []
        for field_name in self.info_sequence():
            if field_name == ApiField.EXT:
                continue
            if skip_missing is True:
                val = info.get(field_name, None)
            else:
                val = info[field_name]
            field_values.append(val)
            if field_name == ApiField.MIME:
                temp_ext = val.split('/')[1]
                field_values.append(temp_ext)
        for idx, field_name in enumerate(self.info_sequence()):
            if field_name == ApiField.NAME:
                cur_ext = get_file_ext(field_values[idx]).replace(".", "").lower()
                if not cur_ext:
                    field_values[idx] = "{}.{}".format(field_values[idx], temp_ext)
                    break
                if temp_ext == 'jpeg' and cur_ext in ['jpg', 'jpeg', 'mpo']:
                    break
                if temp_ext != cur_ext:
                    field_values[idx] = "{}.{}".format(field_values[idx], temp_ext)
                break
        return self.InfoType(*field_values)

    def _remove_batch_api_method_name(self):
        return 'images.bulk.remove'

    def _remove_batch_field_name(self):
        return ApiField.IMAGE_IDS

    def copy_batch(self, dst_dataset_id, ids, change_name_if_conflict=False, with_annotations=False):
        '''
        Copy images with given ids in destination dataset
        :param dst_dataset_id: int
        :param ids: list of integers (raise error if type of ids not listand if images ids have to be from the same dataset)
        :param change_name_if_conflict: bool (if False and images with the same names already exist in destination dataset raise error)
        :param with_annotations: bool (if True - annotations will be copy to dataset too)
        :return: list of images
        '''
        if type(ids) is not list:
            raise RuntimeError("ids parameter has type {!r}. but has to be of type {!r}".format(type(ids), list))

        if len(ids) == 0:
            return

        existing_images = self.get_list(dst_dataset_id)
        existing_names = {image.name for image in existing_images}

        ids_info = self.get_info_by_id_batch(ids)
        temp_ds_ids = {info.dataset_id for info in ids_info}
        if len(temp_ds_ids) > 1:
            raise RuntimeError("Images ids have to be from the same dataset")

        if change_name_if_conflict:
            new_names = [generate_free_name(existing_names, info.name, with_ext=True) for info in ids_info]
        else:
            new_names = [info.name for info in ids_info]
            names_intersection = existing_names.intersection(set(new_names))
            if len(names_intersection) != 0:
                raise RuntimeError('Images with the same names already exist in destination dataset. '
                                   'Please, use argument \"change_name_if_conflict=True\" to automatically resolve '
                                   'names intersection')

        new_images = self.upload_ids(dst_dataset_id, new_names, ids)
        new_ids = [new_image.id for new_image in new_images]

        if with_annotations:
            src_project_id = self._api.dataset.get_info_by_id(ids_info[0].dataset_id).project_id
            dst_project_id = self._api.dataset.get_info_by_id(dst_dataset_id).project_id
            self._api.project.merge_metas(src_project_id, dst_project_id)
            self._api.annotation.copy_batch(ids, new_ids)

        return new_images

    def move_batch(self, dst_dataset_id, ids, change_name_if_conflict=False, with_annotations=False):
        '''
        Move images with given ids in destination dataset
        :param dst_dataset_id: int
        :param ids: list of integers (raise error if type of ids not listand if images ids have to be from the same dataset)
        :param change_name_if_conflict: bool (if False and images with the same names already exist in destination dataset raise error)
        :param with_annotations: bool (if True - annotations will be copy to dataset too)
        :return: list of images
        '''
        new_images = self.copy_batch(dst_dataset_id, ids, change_name_if_conflict, with_annotations)
        self.remove_batch(ids)
        return new_images

    def copy(self, dst_dataset_id, id, change_name_if_conflict=False, with_annotations=False):
        '''
        Copy image with given id in destination dataset
        :param dst_dataset_id: int
        :param id: int
        :param change_name_if_conflict: bool (if False and images with the same names already exist in destination dataset raise error)
        :param with_annotations: bool
        :return: image
        '''
        return self.copy_batch(dst_dataset_id, [id], change_name_if_conflict, with_annotations)[0]

    def move(self, dst_dataset_id, id, change_name_if_conflict=False, with_annotations=False):
        '''
        Move image with given id in destination dataset
        :param dst_dataset_id: int
        :param id: int
        :param change_name_if_conflict: bool (if False and images with the same names already exist in destination dataset raise error)
        :param with_annotations: bool
        :return: image
        '''
        return self.move_batch(dst_dataset_id, [id], change_name_if_conflict, with_annotations)[0]

    def url(self, team_id, workspace_id, project_id, dataset_id, image_id):
        '''
        :param team_id: int
        :param workspace_id: int
        :param project_id: int
        :param dataset_id: int
        :param image_id: int
        :return: url of given image id
        '''
        result = urllib.parse.urljoin(self._api.server_address,
                                      'app/images/{}/{}/{}/{}#image-{}'.format(team_id,
                                                                               workspace_id,
                                                                               project_id,
                                                                               dataset_id,
                                                                               image_id)
                                      )

        return result

    @staticmethod
    def _get_free_name(exist_check_fn, name):
        res_title = name
        suffix = 1

        name_without_ext = get_file_name(name)
        ext = get_file_ext(name)

        while exist_check_fn(res_title):
            res_title = '{}_{:03d}{}'.format(name_without_ext, suffix, ext)
            suffix += 1
        return res_title
