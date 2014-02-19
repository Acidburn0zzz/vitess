# Copyright 2013, Google Inc. All rights reserved.
# Use of this source code is governed by a BSD-style license that can
# be found in the LICENSE file.

import struct

from vtdb import dbexceptions
from vtdb import keyrange_constants


ZK_KEYSPACE_PATH = '/zk/local/vt/ns'

pack_keyspace_id = struct.Struct('!Q').pack

# Represent the SrvKeyspace object from the toposerver, and provide functions
# to extract sharding information from the same.
class Keyspace(object):
  name = None
  db_types = None
  partitions = None
  sharding_col_name = None
  sharding_col_type = None
  served_from = None

  shard_count = None
  shard_max_keys = None # Sorted list of the max keys for each shard.
  shard_names = None # Sorted list of shard names -
                     # these will match the order of shard_max_keys.

  # load this object from a SrvKeyspace object generated by vt
  def __init__(self, name, data):
    self.name = name
    self.db_types = data['TabletTypes']
    self.partitions = data.get('Partitions', {})
    self.sharding_col_name = data.get('ShardingColumnName', "")
    self.sharding_col_type = data.get('ShardingColumnType', keyrange_constants.KIT_UNSET)
    self.served_from = data.get('ServedFrom', None)
    self.shard_count = len(data['Shards'])
    # if we have real values for shards and KeyRange.End, grab them
    if self.shard_count > 1 and data['Shards'][0]['KeyRange']['End'] != "":
      self.shard_max_keys = [shard['KeyRange']['End']
                             for shard in data['Shards']]
    # We end up needing the name for addressing so compute this once.
    self.shard_names = self._make_shard_names()

  def get_shards(self, db_type):
    try:
      return self.partitions[db_type]['Shards']
    except KeyError:
      return []

  def get_shard_count(self, db_type):
    shards = self.get_shards(db_type)
    return len(shards)

  def get_shard_max_keys(self, db_type):
    shards = self.get_shards(db_type)
    shard_max_keys = [shard['KeyRange']['End']
                      for shard in shards]
    return shard_max_keys

  def get_shard_names(self, db_type):
    names = []
    shards = self.get_shards(db_type)
    shard_max_keys = self.get_shard_max_keys(db_type)
    if len(shard_max_keys) == 1 and shard_max_keys[0] == keyrange_constants.MAX_KEY:
      return [keyrange_constants.SHARD_ZERO,]
    for i, max_key in enumerate(self.shard_max_keys):
      min_key = keyrange_constants.MIN_KEY
      if i > 0:
        min_key = self.shard_max_keys[i-1]
      shard_name = '%s-%s' % (min_key.encode('hex').upper(),
                              max_key.encode('hex').upper())
      names.append(shard_name)
    return names

  def keyspace_id_to_shard_index_for_db_type(self, keyspace_id, db_type):
    # Pack this into big-endian and do a byte-wise comparison.
    pkid = pack_keyspace_id(keyspace_id)
    shard_max_keys = self.get_shard_max_keys(db_type)
    if not shard_max_keys:
      raise ValueError('Keyspace is not range sharded', self.name)
    for shard_index, shard_max in enumerate(shard_max_keys):
      if pkid < shard_max:
        break
    # shard_names = self.get_shard_names(db_type)
    # logging.info('Keyspace resolved %s %s %s %s %s %s', keyspace_id,
    #              pkid.encode('hex').upper(), shard_index,
    #              shard_names[shard_index],
    #              [x.encode('hex').upper() for x in shard_max_keys],
    #              shard_names)
    return shard_index

  def keyspace_id_to_shard_index(self, keyspace_id):
    # Pack this into big-endian and do a byte-wise comparison.
    pkid = pack_keyspace_id(keyspace_id)
    if not self.shard_max_keys:
      raise ValueError('Keyspace is not range sharded', self.name)
    for shard_index, shard_max in enumerate(self.shard_max_keys):
      if pkid < shard_max:
        break
    # logging.info('Keyspace resolved %s %s %s %s %s %s', keyspace_id,
    #              pkid.encode('hex').upper(), shard_index,
    #              self.shard_names[shard_index],
    #              [x.encode('hex').upper() for x in self.shard_max_keys],
    #              self.shard_names)
    return shard_index

  def _make_shard_names(self):
    names = []
    if self.shard_max_keys:
      for i, max_key in enumerate(self.shard_max_keys):
        min_key = keyrange_constants.MIN_KEY
        if i > 0:
          min_key = self.shard_max_keys[i-1]
        shard_name = '%s-%s' % (min_key.encode('hex').upper(),
                                max_key.encode('hex').upper())
        names.append(shard_name)
    else:
      # Handle non-range shards
      names = [str(x) for x in xrange(self.shard_count)]
    return names


def read_keyspace(topo_client, keyspace_name):
  try:
    data = topo_client.get_srv_keyspace('local', keyspace_name)
    if not data:
      raise dbexceptions.OperationalError('invalid empty keyspace',
                                          keyspace_name)
    return Keyspace(keyspace_name, data)
  except dbexceptions.OperationalError as e:
    raise e
  except Exception as e:
    raise dbexceptions.OperationalError('invalid keyspace', keyspace_name, e)
