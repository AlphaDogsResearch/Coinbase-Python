from typing import Dict

from common.interface_reference_data import ReferenceData
from common.interface_req_res import ReferenceDataResponse, ReferenceDataRequest
from common.seriallization import SerializableRegistry


# Test your serialization
def test_serialization():
    # Create sample ReferenceData objects
    ref1 = ReferenceData(
        symbol='0GUSDT',
        status='TRADING',
        base_asset='0G',
        quote_asset='USDT',
        price_precision=7,
        quantity_precision=0,
        min_price=0.0001,
        max_price=200.0,
        price_tick_size=0.0001,
        min_lot_size=1.0,
        max_lot_size=1000000000.0,
        lot_step_size=1.0,
        min_market_lot_size=1.0,
        max_market_lot_size=100000000.0,
        market_lot_step_size=1.0,
        min_notional=5.0
    )

    ref2 = ReferenceData(
        symbol='1000000BOBUSDT',
        status='TRADING',
        base_asset='1000000BOB',
        quote_asset='USDT',
        price_precision=7,
        quantity_precision=0,
        min_price=1e-05,
        max_price=200.0,
        price_tick_size=1e-05,
        min_lot_size=1.0,
        max_lot_size=9000000.0,
        lot_step_size=1.0,
        min_market_lot_size=1.0,
        max_market_lot_size=9000000.0,
        market_lot_step_size=1.0,
        min_notional=5.0
    )

    SerializableRegistry.register(ReferenceDataResponse)
    SerializableRegistry.register(ReferenceDataRequest)
    SerializableRegistry.register(ReferenceData)

    # Create Dict[str, ReferenceData]
    reference_dict: Dict[str, ReferenceData] = {
        '0GUSDT': ref1,
        '1000000BOBUSDT': ref2
    }

    # Create ReferenceDataResponse
    response = ReferenceDataResponse(reference_dict)

    # Test 1: Convert to dict
    print("1. Converting to dict...")
    response_dict = response.to_dict()
    print(f"   Type: {type(response_dict)}")
    print(f"   Has reference_data: {'reference_data' in response_dict['data']}")
    print(f"   reference_data type: {type(response_dict['data']['reference_data'])}")
    print(f"   Keys in reference_data: {list(response_dict['data']['reference_data'].keys())}")

    # Test 2: Convert to JSON
    print("\n2. Converting to JSON...")
    json_str = response.to_json(indent=2)
    print(f"   JSON length: {len(json_str)} chars")
    print(f"   First 200 chars:\n{json_str[:200]}...")

    # Test 3: Round-trip serialization
    print("\n3. Testing round-trip...")
    restored_response = ReferenceDataResponse.from_json(json_str)
    print(f"   Restored type: {type(restored_response)}")
    print(f"   Has reference_data: {hasattr(restored_response, 'reference_data')}")
    print(f"   reference_data type: {type(restored_response.reference_data)}")

    # Test 4: Verify data integrity
    print("\n4. Verifying data integrity...")
    original_symbols = list(response.reference_data.keys())
    restored_symbols = list(restored_response.reference_data.keys())
    print(f"   Original symbols: {original_symbols}")
    print(f"   Restored symbols: {restored_symbols}")
    print(f"   Symbols match: {original_symbols == restored_symbols}")

    if original_symbols == restored_symbols:
        for symbol in original_symbols:
            orig = response.reference_data[symbol]
            restored = restored_response.reference_data[symbol]
            print(f"   {symbol}:")
            print(f"     Symbol matches: {orig.symbol == restored.symbol}")
            print(f"     Status matches: {orig.status == restored.status}")
            print(f"     Min price matches: {orig.min_price == restored.min_price}")

    return response, json_str, restored_response


# Run the test
if __name__ == "__main__":
    response, json_str, restored = test_serialization()

    # You can also save to file
    with open('reference_data.json', 'w') as f:
        f.write(json_str)

    print(f"\n✅ Successfully serialized Dict[str, ReferenceData]!")
    print(f"   File saved: reference_data.json")