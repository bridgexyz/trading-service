import asyncio
import lighter

BASE_URL = "https://mainnet.zklighter.elliot.ai"
L1_ADDRESS = "0x636B6094942B10f17cD15A650d4D2C7e46256497"

async def main():
    client = lighter.ApiClient(lighter.Configuration(host=BASE_URL))
    resp = await lighter.AccountApi(client).accounts_by_l1_address(l1_address=L1_ADDRESS)
    print(resp.sub_accounts[0].index)
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())