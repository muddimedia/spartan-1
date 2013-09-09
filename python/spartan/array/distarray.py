#!/usr/bin/env python

from . import tile, extent
import spartan
from spartan import util
from spartan.util import Assert
import numpy as np
import itertools

# number of elements per tile
TILE_SIZE = 100000

def find_shape(extents):
  #util.log('Finding shape... %s', extents)
  return np.max([ex.lr for ex in extents], axis=0)


def get_data(data, index):
  if isinstance(data, tuple):
    return tuple([get_data(d, index) for d in data])
  if not isinstance(data, np.ndarray):
    data = np.array(data)
  if not data.shape:
    data = data.reshape((1,))
  return data[index]


def extents_for_region(extents, tile_extent):
  Assert.isinstance(extents, set)
  for ex in extents:
    intersection = extent.intersection(ex, tile_extent)
    if intersection is not None:
      yield (ex, intersection)
      

  
def find_matching_tile(array, tile_extent):
  for ex in array.extents():
    ul_diff = tile_extent.ul - ex.ul
    lr_diff = ex.lr - tile_extent.lr
    if np.all(ul_diff >= 0) and np.all(lr_diff >= 0):
      # util.log('%s matches %s', ex, tile_extent)
      return array.tile_for_extent(ex)
  
  raise Exception, 'No matching tile_extent!' 
 
 
def take_first(a,b):
  return a

accum_replace = tile.TileAccum(take_first)
accum_min = tile.TileAccum(np.minimum)
accum_max = tile.TileAccum(np.maximum)
accum_sum = tile.TileAccum(np.add)


  
class NestedSlice(object):
  def __init__(self, extent, subslice):
    self.extent = extent
    self.subslice = subslice
    
  def __eq__(self, other):
    Assert.isinstance(other, extent.TileExtent)
    return self.extent == other 
  
  def __hash__(self):
    return hash(self.extent)


class TileSelector(object):
  def __call__(self, k, v):
    #util.log('Selector called for %s', k)
    if isinstance(k, extent.TileExtent): 
      return v[:]
    if isinstance(k, NestedSlice):
      result = v[k.subslice]
#       print k.extent, k.subslice, result.shape
      return result
    raise Exception, "Can't handle type %s" % type(k)
  


def compute_splits(shape):
  '''Split an array of shape ``shape`` into `Extent`s containing roughly `TILE_SIZE` elements.
  
  :rtype: list of `Extent`
  '''
    
  if len(shape) == 0:
    return [extent.TileExtent([], [], ())]
 
  weight = 1
  splits = [None] * len(shape)
  
  # split each dimension into tiles.  the first dimension
  # is kept contiguous if possible.
  for dim in reversed(range(len(shape))):
    step = max(1, TILE_SIZE / weight)
    dim_splits = []
    for i in range(0, shape[dim], step):
      dim_splits.append((i, min(shape[dim] - i,  step)))
      
    splits[dim] = dim_splits
    weight *= shape[dim]
 
  result = []
  for slc in itertools.product(*splits):
    ul, lr = zip(*slc)
    ex = extent.TileExtent(ul, lr, shape)
    result.append(ex)
  
  return set(result)
    
def _create_rand(extent, data):
  data[:] = np.random.rand(*extent.shape)

def _create_randn(extent, data):
  data[:] = np.random.randn(*extent.shape)
  
def _create_ones(extent, data):
#   util.log('Updating %s, %s', extent, data)
  data[:] = 1

def _create_zeros(extent, data):
  data[:] = 0

def _create_range(extent, data):
  Assert.eq(extent.shape, data.shape)
  pos = extent.ravelled_pos()
  sz = np.prod(extent.shape)
  data[:] = np.arange(pos, pos+sz).reshape(extent.shape)
  
def randn(master, *shape):
  return create_with(master, shape, _create_randn)

def rand(master, *shape):
  return create_with(master, shape, _create_rand)

def ones(master, shape):
  return create_with(master, shape, _create_ones)

def arange(master, shape):
  return create_with(master, shape, _create_range)


def from_table(table):
  '''
  Construct a distarray from an existing table.
  Keys must be of type `Extent`, values of type `Tile`.
  
  Shape is computed as the maximum range of all extents.
  
  Dtype is taken from the dtype of the tiles.
  
  :param table:
  '''
  extents = table.keys()
  Assert.no_duplicates(extents)
  
  if not extents:
    shape = tuple()
  else:
    shape = find_shape(extents)
  
  if len(extents) > 0:
    t = table[extents[0]]
    # (We're not actually returning a tile, as the selector instead
    #  is returning just the underlying array.  Sigh).  
    # Assert.isinstance(t, tile.Tile)
    dtype = t.dtype
  else:
    # empty table; default dtype.
    dtype = np.float
  
  extents = set(extents)
  return DistArray(shape=shape, dtype=dtype, table=table, extents=extents)

def create(master, shape, 
           dtype=np.float, 
           sharder=spartan.ModSharder(),
           combiner=None,
           reducer=accum_replace):
  
  dtype = np.dtype(dtype)
  shape = tuple(shape)
  total_elems = np.prod(shape)
  extents = compute_splits(shape)
  
  util.log('Creating array of shape %s with %d tiles', 
           shape, len(extents))

  table = master.create_table(sharder, combiner, reducer, TileSelector())
  for ex in extents:
    ex_tile = tile.Tile(ex, data=None, dtype=dtype)
    table.update(ex, ex_tile)
  
  return DistArray(shape=shape, dtype=dtype, table=table, extents=extents)

def create_with(master, shape, init_fn):
  d = create(master, shape)
  spartan.map_inplace(d.table, init_fn)
  return d 


class DistArray(object):
  def __init__(self, shape, dtype, table, extents):
    self.shape = shape
    self.dtype = dtype
    self.table = table
    self.extents = extents
  
  def id(self):
    return self.table.id()
   
  def map_to_table(self, fn):
    return spartan.map_items(self.table, fn)
  
  def map_tiles(self, fn):
    return self.map_to_table(fn)
  
  def map_to_array(self, fn):
    return from_table(self.map_to_table(fn))
  
  def map_inplace(self, fn):
    spartan.map_inplace(self.table, fn)
    return self
  
  def foreach(self, fn):
    return spartan.foreach(self.table, fn)
  
  def __repr__(self):
    return 'DistArray(shape=%s, dtype=%s)' % (self.shape, self.dtype)
  
  def _get(self, extent):
    return self.table.get(extent)
  
  def ensure(self, region):
    '''
    Return a local numpy array for the given region.
    
    If necessary, data will be copied from remote hosts to fill the region.    
    :param region: `Extent` indicating the region to fetch.
    '''
    Assert.isinstance(region, extent.TileExtent)
    
    # special case exact match against a tile 
    if region in self.extents:
      #util.log('Exact match.')
      ex, intersection = region, region
      return self.table.get(NestedSlice(ex, extent.offset_slice(ex, intersection)))

    splits = list(extents_for_region(self.extents, region))
    
    #util.log('Target shape: %s, %d splits', region.shape, len(splits))
    tgt = np.ndarray(region.shape)
    for ex, intersection in splits:
      dst_slice = extent.offset_slice(region, intersection)
      src_slice = self.table.get(NestedSlice(ex, extent.offset_slice(ex, intersection)))
      tgt[dst_slice] = src_slice
    return tgt
    #return tile.data[]
    
  def update(self, region, data):
    Assert.isinstance(region, extent.TileExtent)
    Assert.eq(region.shape, data.shape)

    #util.log('%s %s', self.table.id(), self.extents)
    # exact match
    if region in self.extents:
      #util.log('EXACT: %d %s ', self.table.id(), region)
      self.table.update(region, tile.make_tile(region, data))
      return
    
    splits = list(extents_for_region(self.extents, region))
    for dst_key, intersection in splits:
      #util.log('%d %s %s %s', self.table.id(), region, dst_key, intersection)
      src_slice = extent.offset_slice(region, intersection)
      update_tile = tile.make_tile(intersection, data[src_slice])
      self.table.update(dst_key, update_tile)
    
  
  def __getitem__(self, idx):
    if isinstance(idx, extent.TileExtent):
      return self.ensure(idx)
    
    if np.isscalar(idx):
      return self[idx:idx+1][0]
    
    ex = extent.from_slice(idx, self.shape)
    return self.ensure(ex)
  
  def glom(self):
    util.log('Glomming: %s', self.shape)
    ex = extent.TileExtent([0] * len(self.shape), self.shape, self.shape)
    return self.ensure(ex)



def slice_mapper(ex, tile, **kw):
  fn = kw['fn']
  slice_extent = kw['slice']
  kernel = kw['kernel']
  
  intersection = extent.intersection(slice_extent, ex)
  if intersection is None:
    return []
  
  subslice = extent.offset_slice(ex, intersection)
  subtile = tile[subslice]
  
  return fn(intersection, subtile)
  

class Slice(object):
  def __init__(self, darray, idx):
    Assert.isinstance(idx, extent.TileExtent)
    Assert.isinstance(darray, DistArray)
    self.darray = darray
    self.idx = idx
    self.shape = self.idx.shape
    intersections = [extent.intersection(self.idx, ex) for ex in self.darray]
    intersections = [ex for ex in intersections if ex is not None]
    self.extents = intersections
    
  def map_to_array(self, fn):
    return from_table(self.map_to_table(fn))
  
  def map_tiles(self, fn):
    return self.map_to_table(fn)
  
  def map_to_table(self, fn):
    return spartan.map_items(self.darray.table, 
                             slice_mapper,
                             fn = fn,
                             slice_extent = self.idx)

  def glom(self):
    return self.darray.ensure(self.idx)

  def __getitem__(self, idx):
    ex = extent.compute_slice(self.idx, idx)
    return self.darray.ensure(ex)



class Broadcast(object):
  '''A broadcast object mimics the behavior of Numpy broadcasting.
  
  Takes an input of shape (x, y) and a desired output shape (x, y, z),
  the broadcast object reports shape=(x,y,z) and overrides __getitem__
  to return the appropriate values.
  '''
  def __init__(self, base, shape):
    Assert.isinstance(base, (np.ndarray, DistArray))
    Assert.isinstance(shape, tuple)
    self.base = base
    self.shape = shape
  
  def __getitem__(self, idx):
    pass
  
  def __repr__(self):
    return 'Broadcast(%s -> %s)' % (self.base, self.shape)


def broadcast(*args):
  if len(args) == 1:
    return args[0]
 
  shapes = [x.shape for x in args]
  dims = [len(shape) for shape in shapes]
  max_dim = max(dims)
  new_shape = []
  
  # prepend filler dimensions for smaller arrays
  for i in range(len(shapes)):
    diff = max_dim - len(shapes[i])
    shapes[i] = [1] * diff + shapes[i]
  
  # check shapes are valid; there should be at most one unique
  # shape.
  for axis in range(max_dim):
    axis_shape = set(s[axis] for s in shapes)
    Assert.le(axis_shape, 2, 'Mismatched shapes for broadcast: ' + shapes)
    
  results = []
  for i in range(len(args)):
    results.append(Broadcast(args[i], shapes[i]))
    
  util.log('Broadcast result: %s', results)
  return results
    
      
    
    
    
  