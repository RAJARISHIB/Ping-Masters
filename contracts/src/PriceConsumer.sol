// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title PriceConsumer
 * @notice Dual-currency BNB/USD and BNB/INR price oracle for Ping-Masters.
 *         Deployed on BNB Smart Chain Testnet.
 *
 *  PRICE DECIMAL CONVENTION  (8 decimals, same as Chainlink)
 *   USD  $300.00     ->  30_000_000_000      (3e10)
 *   INR  Rs25000.00  ->  2_500_000_000_000   (2.5e12)
 *
 *  The FastAPI bot calls updateBothPrices() every ~3 seconds so both feeds
 *  stay in sync with BSC block times.
 *
 *  The Currency enum is defined here so LendingEngine can reference
 *  PriceConsumer.Currency without a separate types file.
 */
contract PriceConsumer {

    // ─── TYPES ───────────────────────────────────────────────────────────────

    /// @notice Supported fiat currencies. 0 = USD, 1 = INR.
    enum Currency { USD, INR }

    // ─── CONSTANTS ───────────────────────────────────────────────────────────

    uint8 public constant DECIMALS = 8;

    // ─── STATE ───────────────────────────────────────────────────────────────

    /// @notice prices[0] = BNB/USD,  prices[1] = BNB/INR  (both 8-decimal).
    mapping(uint8 => uint256) private _prices;

    /// @notice Last update timestamp per currency (0=USD, 1=INR).
    mapping(uint8 => uint256) public lastUpdatedAt;

    address public owner;

    // ─── EVENTS ──────────────────────────────────────────────────────────────

    event PriceUpdated(
        Currency indexed currency,
        uint256 oldPrice,
        uint256 newPrice,
        uint256 timestamp
    );
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    // ─── ERRORS ──────────────────────────────────────────────────────────────

    error Unauthorized();
    error InvalidPrice();
    error StalePrice(uint256 lastUpdated, uint256 maxAge);

    // ─── CONSTRUCTOR ─────────────────────────────────────────────────────────

    /**
     * @param initialUSDPrice  e.g. 30_000_000_000  for $300.00  (8 decimals)
     * @param initialINRPrice  e.g. 2_500_000_000_000  for Rs25000  (8 decimals)
     */
    constructor(uint256 initialUSDPrice, uint256 initialINRPrice) {
        if (initialUSDPrice == 0 || initialINRPrice == 0) revert InvalidPrice();
        owner = msg.sender;
        _prices[uint8(Currency.USD)] = initialUSDPrice;
        _prices[uint8(Currency.INR)] = initialINRPrice;
        lastUpdatedAt[uint8(Currency.USD)] = block.timestamp;
        lastUpdatedAt[uint8(Currency.INR)] = block.timestamp;
        emit PriceUpdated(Currency.USD, 0, initialUSDPrice, block.timestamp);
        emit PriceUpdated(Currency.INR, 0, initialINRPrice, block.timestamp);
    }

    // ─── MODIFIERS ───────────────────────────────────────────────────────────

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    // ─── READ ────────────────────────────────────────────────────────────────

    /**
     * @notice Get BNB price for a specific currency with optional staleness check.
     * @param  currency  Currency.USD or Currency.INR.
     * @param  maxAge    Max seconds since last update; 0 = skip check.
     */
    function getLatestPrice(Currency currency, uint256 maxAge)
        external
        view
        returns (uint256)
    {
        uint8 key = uint8(currency);
        if (maxAge > 0 && block.timestamp - lastUpdatedAt[key] > maxAge)
            revert StalePrice(lastUpdatedAt[key], maxAge);
        return _prices[key];
    }

    /// @notice Convenience overload — no staleness check.
    function getLatestPrice(Currency currency) external view returns (uint256) {
        return _prices[uint8(currency)];
    }

    /**
     * @notice Returns both prices in one call — saves gas for the monitoring bot.
     * @return usdPrice  BNB/USD with 8 decimals.
     * @return inrPrice  BNB/INR with 8 decimals.
     */
    function getBothPrices()
        external
        view
        returns (uint256 usdPrice, uint256 inrPrice)
    {
        usdPrice = _prices[uint8(Currency.USD)];
        inrPrice = _prices[uint8(Currency.INR)];
    }

    // ─── WRITE (owner / FastAPI bot) ─────────────────────────────────────────

    /// @notice Update a single currency price.
    function updatePrice(Currency currency, uint256 newPrice) external onlyOwner {
        if (newPrice == 0) revert InvalidPrice();
        uint8   key = uint8(currency);
        uint256 old = _prices[key];
        _prices[key]       = newPrice;
        lastUpdatedAt[key] = block.timestamp;
        emit PriceUpdated(currency, old, newPrice, block.timestamp);
    }

    /**
     * @notice Update both prices atomically — preferred so the bot refreshes
     *         USD and INR in the same block to avoid cross-currency arbitrage.
     */
    function updateBothPrices(
        uint256 newUSDPrice,
        uint256 newINRPrice
    ) external onlyOwner {
        if (newUSDPrice == 0 || newINRPrice == 0) revert InvalidPrice();
        uint256 oldUSD = _prices[uint8(Currency.USD)];
        uint256 oldINR = _prices[uint8(Currency.INR)];
        _prices[uint8(Currency.USD)]       = newUSDPrice;
        _prices[uint8(Currency.INR)]       = newINRPrice;
        lastUpdatedAt[uint8(Currency.USD)] = block.timestamp;
        lastUpdatedAt[uint8(Currency.INR)] = block.timestamp;
        emit PriceUpdated(Currency.USD, oldUSD, newUSDPrice, block.timestamp);
        emit PriceUpdated(Currency.INR, oldINR, newINRPrice, block.timestamp);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert InvalidPrice();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function decimals() external pure returns (uint8) {
        return DECIMALS;
    }
}
