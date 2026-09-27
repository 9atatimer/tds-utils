// storage.fake.test.ts -- the StoragePort fake honours the port contract.

import { FakeStorage } from '../../fakes/FakeStorage.js';
import { describeStorageContract } from '../../port-contracts/storage.contract.js';

describeStorageContract('FakeStorage', () => new FakeStorage());
